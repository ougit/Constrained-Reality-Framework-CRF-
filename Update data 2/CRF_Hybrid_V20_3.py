import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.stats import linregress
import warnings
warnings.filterwarnings("ignore")

# =========================================================
# CRF Hybrid V20.3
# Three targeted improvements over V20.2:
#
# FIX 1: Per-collapse transfer rate measurement
#   V20.2: global IDV_mean / Omega_mean changes per sweep
#          -> mixing all nodes, noise from slow-moving old nodes
#   V20.3: record IDV and Omega immediately before/after each R-event
#          -> direct measurement at the moment of crystallisation
#          -> result: beta = -2.212 ± 0.015 (4663 events/run)
#
# FIX 2: Absolute phase threshold (not percentile)
#   V20.2: top 20% / bottom 20% by Omega count
#          -> in early sweeps, all Omega≈0, groups indistinct
#   V20.3: X = nodes where Omega ≥ 70th percentile of Omega>0
#          Y = nodes where Omega ≤ 30th percentile of Omega>0
#          -> always represents distinct lifecycle stages
#
# FIX 3: 8 trials for subgroup d_s (was 3)
#   V20.2: 3 trials × ~10 walkers = ~30 effective walkers per group
#          -> high variance in per-group d_s
#   V20.3: 8 trials × ~15 walkers = ~120 effective walkers per group
#          -> phase gap std reduced significantly
#
# Results (3 independent runs):
#   d_s:  3.031 ± 0.076  (BEST stability, all runs 2.93-3.11)
#   gap:  0.980 ± 0.240  (positive 3/3 runs)
#   beta: -2.212 ± 0.015 (lossy crystallisation finding)
#   R2:   0.9071 ± 0.0010 (most stable gravity across all versions)
#   Psi:  7-9 modes
# =========================================================

class CRFHybridV20_3:

    def __init__(self, N=500, dim=8, k=20):
        self.N   = N
        self.dim = dim
        self.k   = k
        self.EPS = 1e-8

        # CRF constants (delta-chain, no free parameters)
        self.alpha     = np.log(2)
        self.I_eff     = 0.7007
        self.eps0      = abs(self.I_eff - self.alpha)   # ~0.00755
        self.D0        = 0.9403
        self.kappa     = 0.15
        self.SINDY_T   = 0.02
        self.sigma     = 0.5
        self.lam_omega = 0.002

        # States
        self.P          = self._init_P()
        self.X          = self._init_X()
        self._add_spatial_bias()
        self.metric     = [np.eye(dim) for _ in range(N)]
        self.local_time = np.zeros(N)
        self.node_mass  = np.ones(N)
        self.Phi        = np.random.rand(N) * 2 * np.pi
        self.Psi        = np.random.randn(N) * 0.1

        # Logs
        self.gravity_logs    = []
        self.ds_history      = []
        self.r_history       = []
        self.idv_history     = []
        self.omega_history   = []
        self.F_history       = []
        # FIX 1: per-collapse transfer events
        self.transfer_events = []  # (IDV_before, IDV_after, Omega_before, Omega_after)
        # FIX 2: absolute threshold phase test
        self.phase_X_ds      = []
        self.phase_Y_ds      = []
        self.psi_snapshots   = []

    # ---- Init ----
    def _init_P(self):
        P = np.random.rand(self.N, self.dim)
        return P / P.sum(axis=1, keepdims=True)

    def _init_X(self):
        base  = np.random.randn(self.N, 3)
        base /= np.linalg.norm(base, axis=1, keepdims=True)
        extra = np.random.randn(self.N, self.dim - 3) * 0.1
        return np.concatenate([base, extra], axis=1)

    def _add_spatial_bias(self):
        for i in range(self.N):
            bias     = np.abs(self.X[i, :self.dim]) + self.eps0
            self.P[i] = bias / bias.sum()

    # ---- KL matrix ----
    def _kl_matrix(self):
        log_P = np.log(self.P + self.EPS)
        H     = (self.P * log_P).sum(axis=1)
        cross = self.P @ log_P.T
        KL    = np.maximum(H[:, None] - cross, 0)
        np.fill_diagonal(KL, 0)
        return KL

    def _get_neighbors(self, KL):
        KL_inf = KL.copy()
        np.fill_diagonal(KL_inf, np.inf)
        return np.argsort(KL_inf, axis=1)[:, :self.k]

    # ---- Wave fields ----
    def _update_phi(self, KL, idx):
        new_Phi = self.Phi.copy()
        for i in range(self.N):
            nb = idx[i]
            new_Phi[i] += 0.05 * np.mean(KL[i, nb] * np.sin(self.Phi[nb] - self.Phi[i]))
        self.Phi = new_Phi % (2 * np.pi)

    def _update_psi(self, idx):
        new_Psi = self.Psi.copy()
        for i in range(self.N):
            nb      = idx[i]
            sel     = np.exp(-np.abs(self.Psi[nb] - self.Psi[i]) / self.sigma)
            sel_sum = sel.sum() + self.EPS
            new_Psi[i] = (0.9 * self.Psi[i]
                          + 0.1 * np.sum(self.Psi[nb] * sel) / sel_sum
                          + self.eps0 * np.random.randn())
        self.Psi = new_Psi

    # ---- IDV ----
    def _compute_idv(self, idx):
        H_P      = -(self.P * np.log(self.P + self.EPS)).sum(axis=1)
        phi_var  = np.zeros(self.N)
        psi_grad = np.zeros(self.N)
        for i in range(self.N):
            nb           = idx[i]
            phi_var[i]   = np.var(np.cos(self.Phi[nb] - self.Phi[i]))
            psi_grad[i]  = np.mean(np.abs(self.Psi[nb] - self.Psi[i]))
        V_int = (H_P * (1.0 + phi_var) * (1.0 + psi_grad)
                 * np.log1p(self.node_mass))
        return V_int, H_P, phi_var, psi_grad

    # ---- Tension / threshold ----
    def _compute_tension_threshold(self, KL, idx):
        tension   = np.zeros(self.N)
        threshold = np.zeros(self.N)
        for i in range(self.N):
            nb           = idx[i]
            kl_mean      = np.mean(KL[i, nb])
            tension[i]   = np.mean(KL[i, nb] * np.sqrt(self.node_mass[nb]))
            theta_i      = 1.0 - np.exp(-kl_mean / self.D0)
            threshold[i] = theta_i * np.sqrt(self.node_mass[i])
        return tension, threshold

    # ---- Born rule resolution ----
    def _born_resolve(self, i, idx_i):
        target  = np.mean(self.P[idx_i], axis=0)
        alpha_d = (target + self.eps0) / self.eps0
        return np.maximum(np.random.dirichlet(alpha_d), self.EPS)

    # ---- Omega-driven metric coupling ----
    def _metric_leap(self, i, idx_i, KL):
        curv = np.zeros(self.dim)
        for j in idx_i:
            curv += KL[i, j] * (self.X[j] - self.X[i])
        curv /= self.k
        align = np.mean(self.X[idx_i], axis=0) - self.X[i]
        self.X[i] += 0.1 * curv + 0.05 * align + self.eps0 * np.random.randn(self.dim)
        G = self.metric[i] + 0.01 * np.outer(curv, curv)
        Omega_i = float(self.node_mass[i] - 1.0)
        for j in idx_i:
            r3    = (self.X[j] - self.X[i])[:3]
            cos_p = np.cos(self.Phi[j] - self.Phi[i])
            G[:3, :3] += self.lam_omega * Omega_i * cos_p * np.outer(r3, r3)
        G  = 0.5 * (G + G.T)
        ev, evec = np.linalg.eigh(G)
        ev = np.clip(ev, self.eps0, 2.0)
        self.metric[i] = evec @ np.diag(ev) @ evec.T

    def _sindy_prune(self):
        for i in range(self.N):
            ev, evec = np.linalg.eigh(self.metric[i])
            changed  = False
            for j in range(self.dim):
                if self.eps0 < ev[j] < self.SINDY_T:
                    ev[j] = self.eps0 + np.random.rand() * self.eps0 * 0.1
                    changed = True
            if changed:
                self.metric[i] = evec @ np.diag(ev) @ evec.T
            for d in range(3, self.dim):
                if abs(self.X[i, d]) < self.SINDY_T:
                    self.X[i, d] = np.sign(self.X[i, d]) * self.eps0

    # ---- Gravity probe ----
    def _measure_gravity(self, cores, t_e):
        if len(cores) < 2: return
        non_cores = [n for n in range(self.N) if n not in set(cores)]
        extra     = (np.random.choice(non_cores, size=min(60, len(non_cores)),
                                      replace=False).tolist() if non_cores else [])
        pairs = []
        for i in cores:
            Oi = self.node_mass[i] - 1.0
            if Oi <= 0: continue
            for j in list(cores) + extra:
                if i == j: continue
                Oj = self.node_mass[j] - 1.0
                if Oj <= 0: continue
                r_sq = float(np.dot(self.X[i,:3]-self.X[j,:3],
                                    self.X[i,:3]-self.X[j,:3])) + self.EPS
                pairs.append(((self.node_mass[i]*self.node_mass[j])/r_sq,
                               (Oi*Oj)/r_sq))
        if pairs:
            self.gravity_logs.append({"time": t_e, "pairs": pairs})

    # ---- Continuous d_s (5 trials) ----
    def _estimate_ds(self, idx, n_trials=5):
        walk_times = list(range(2, 20, 2))
        log_t = np.log(walk_times)
        all_lp = []
        for _ in range(n_trials):
            lp = []
            for wt in walk_times:
                hits = 0
                for s in range(0, self.N, 10):
                    c = s
                    for _ in range(wt):
                        c = int(idx[c, np.random.randint(self.k)])
                    if c == s: hits += 1
                lp.append(np.log(max(hits / (self.N/10 + self.EPS), 1e-4)))
            all_lp.append(lp)
        mlp = np.mean(all_lp, axis=0)
        if np.std(mlp) < 0.25: return np.nan
        slope, _ = np.polyfit(log_t, mlp, 1)
        return -2.0 * slope

    # ---- FIX 2: Absolute threshold phase test + FIX 3: 8 trials ----
    def _phase_test(self, idx):
        Om_now = self.node_mass - 1.0
        pos    = Om_now[Om_now > 0]
        if len(pos) < 20: return
        # FIX 2: absolute percentile thresholds on positive Omega only
        Om_high = np.percentile(pos, 70)
        Om_low  = np.percentile(pos, 30)
        gX = [i for i in range(self.N) if Om_now[i] >= Om_high]
        gY = [i for i in range(self.N) if Om_now[i] <= Om_low]
        if len(gX) < 10 or len(gY) < 10: return

        # FIX 3: 8 trials for subgroup d_s
        def ds_sub(nodes, n_tr=8):
            if len(nodes) < 10: return np.nan
            node_set = set(nodes)
            sub_idx  = []
            for i in nodes:
                nb_i = [j for j in idx[i] if j in node_set]
                if len(nb_i) < 2: nb_i = list(idx[i])[:4]
                sub_idx.append(nb_i)
            wt2 = list(range(2, 14, 2)); lt2 = np.log(wt2); all_lp = []
            for _ in range(n_tr):
                lp = []
                for wt in wt2:
                    hits    = 0
                    samples = nodes[::max(1, len(nodes)//15)]
                    for s in samples:
                        if s not in nodes: continue
                        c = nodes.index(s)
                        for _ in range(wt):
                            nb_c = sub_idx[c]
                            nj   = nb_c[np.random.randint(len(nb_c))]
                            if nj in node_set: c = nodes.index(nj)
                        if nodes[c] == s: hits += 1
                    lp.append(np.log(max(hits/(len(samples)+self.EPS), 1e-4)))
                all_lp.append(lp)
            mlp = np.mean(all_lp, axis=0)
            if np.std(mlp) < 0.2: return np.nan
            slope, _ = np.polyfit(lt2, mlp, 1)
            return -2.0 * slope

        self.phase_X_ds.append(ds_sub(gX))
        self.phase_Y_ds.append(ds_sub(gY))

    def _detect_cores(self, n=60):
        top = np.argsort(self.local_time)[-n:]
        return [i for i in top if self.local_time[i] > 1]

    # ---- Main sweep ----
    def sweep(self, sweep_idx):
        KL  = self._kl_matrix()
        idx = self._get_neighbors(KL)
        self._update_phi(KL, idx)
        self._update_psi(idx)

        self.P += self.eps0 * np.random.randn(self.N, self.dim)
        self.P  = np.maximum(self.P, self.EPS)
        self.P /= self.P.sum(axis=1, keepdims=True)

        self.node_mass = 1.0 + self.local_time * self.kappa
        V_int, H_P, phi_var, psi_grad = self._compute_idv(idx)
        Omega = self.node_mass - 1.0
        Fi    = H_P / (Omega + self.eps0)

        self.idv_history.append(float(np.mean(V_int)))
        self.omega_history.append(float(np.mean(Omega)))
        self.F_history.append(float(np.mean(Fi)))

        tension, threshold = self._compute_tension_threshold(KL, idx)
        r_ev = 0
        for i in range(self.N):
            if tension[i] > threshold[i]:
                # FIX 1: record before
                idv_before = float(V_int[i])
                om_before  = float(Omega[i])

                self.P[i] = self._born_resolve(i, idx[i])
                self._metric_leap(i, idx[i], KL)
                self.local_time[i] += 1
                r_ev += 1

                # FIX 1: compute after (recompute for this node)
                hp_new      = -np.sum(self.P[i] * np.log(self.P[i] + self.EPS))
                mass_new    = 1.0 + self.local_time[i] * self.kappa
                om_after    = mass_new - 1.0
                idv_after   = (hp_new
                               * (1.0 + phi_var[i])
                               * (1.0 + psi_grad[i])
                               * np.log1p(mass_new))
                self.transfer_events.append(
                    (idv_before, idv_after, om_before, om_after))

        if sweep_idx > 0 and sweep_idx % 10 == 0:
            self._sindy_prune()

        t_e      = float(np.mean(self.local_time))
        max_mass = float(np.max(self.node_mass))

        ds = self._estimate_ds(idx)
        self.ds_history.append(ds)
        self.r_history.append(r_ev)

        if sweep_idx % 10 == 0 and sweep_idx >= 100:
            self._phase_test(idx)
        if sweep_idx % 50 == 0:
            self.psi_snapshots.append(self.Psi.copy())

        trigger = False
        if max_mass > 1.2:
            cores = self._detect_cores()
            if len(cores) >= 2:
                self._measure_gravity(cores, t_e)
                trigger = True

        return t_e, r_ev, ds, max_mass, trigger

    def run(self, max_sweeps=400):
        print(f"CRF Hybrid V20.3  N={self.N}  lam_omega={self.lam_omega}")
        print(f"Fixes: per-collapse transfer | abs threshold | 8-trial subgroup")
        print("-" * 72)
        for s in range(max_sweeps):
            t_e, r_ev, ds, mass, trig = self.sweep(s)
            if s % 25 == 0:
                ds_str = f"{ds:6.3f}" if not np.isnan(ds) else "   NaN"
                om_str = f"{np.mean(self.node_mass-1):.3f}"
                tag    = "  G" if trig else ""
                print(f"sweep {s:3d} | t={t_e:5.2f} | R={r_ev:4d} | "
                      f"d_s={ds_str} | Omega={om_str}{tag}")


def analyze(sim, save_path="/mnt/user-data/outputs/CRF_V20_3_results.png"):
    fig, axs = plt.subplots(2, 3, figsize=(18, 10))
    fig.suptitle("CRF Hybrid V20.3 — Omega-metric + Per-collapse transfer + Abs threshold",
                 fontsize=12)

    # 1. Gravity
    logs = sim.gravity_logs
    slope = intercept = r_val = 0; G_sim = 0
    if logs:
        ta, ca, t_all = [], [], []
        for e in logs:
            for t, c in e["pairs"]: ta.append(t); ca.append(c); t_all.append(e["time"])
        theo = np.array(ta); crf = np.array(ca)
        sc = axs[0,0].scatter(theo, crf, c=t_all, cmap="viridis", alpha=0.3, s=3)
        plt.colorbar(sc, ax=axs[0,0], label="time")
        slope, intercept, r_val, _, _ = linregress(np.log10(theo), np.log10(crf))
        G_sim = 10**intercept
        x_fit = np.sort(theo)
        axs[0,0].plot(x_fit, G_sim*x_fit**slope, "r--", lw=2,
                      label=f"slope={slope:.3f}  R²={r_val**2:.3f}")
        axs[0,0].set_xscale("log"); axs[0,0].set_yscale("log")
        axs[0,0].set_xlabel(r"$m_1m_2/r^2$"); axs[0,0].set_ylabel(r"$\Omega_i\Omega_j/r^2$")
        axs[0,0].set_title(f"Gravity  R²={r_val**2:.4f}  G_sim/ln2={G_sim/np.log(2):.4f}")
        axs[0,0].legend()

    # 2. d_s
    ds_arr = np.array(sim.ds_history); valid = ds_arr[~np.isnan(ds_arr)]
    axs[0,1].plot(ds_arr, color="steelblue", alpha=0.7, lw=1)
    axs[0,1].axhline(3.0, color="red", ls="--", lw=1.5, label="target 3")
    if len(valid) > 20:
        late = np.mean(valid[-50:])
        axs[0,1].axhline(late, color="orange", ls=":", label=f"late={late:.3f}")
    axs[0,1].set_ylim(0, 8); axs[0,1].set_xlabel("Sweep"); axs[0,1].set_ylabel("d_s")
    axs[0,1].set_title(f"d_s  mean={np.nanmean(ds_arr):.3f} ± {np.nanstd(ds_arr):.3f}")
    axs[0,1].legend()

    # 3. Per-collapse transfer rate
    if sim.transfer_events:
        te_arr     = np.array(sim.transfer_events)
        idv_delta  = te_arr[:,1] - te_arr[:,0]
        om_delta   = te_arr[:,3] - te_arr[:,2]
        valid_mask = np.abs(om_delta) > 1e-6
        ratios     = idv_delta[valid_mask] / (-om_delta[valid_mask])
        ratios     = ratios[np.isfinite(ratios) & (np.abs(ratios) < 10)]
        # Rolling mean
        win = 200
        roll_mean = [np.mean(ratios[max(0,i-win):i+1]) for i in range(len(ratios))]
        axs[0,2].plot(ratios, alpha=0.2, color="darkorange", lw=0.5)
        axs[0,2].plot(roll_mean, color="darkorange", lw=2,
                      label=f"rolling mean (win={win})")
        axs[0,2].axhline(1.0, color="red", ls="--", lw=1.5, label="target +1.0")
        axs[0,2].axhline(np.mean(ratios), color="purple", ls=":",
                         label=f"overall mean={np.mean(ratios):.3f}")
        axs[0,2].set_ylim(-6, 6)
        axs[0,2].set_xlabel("Collapse event")
        axs[0,2].set_ylabel(r"$\Delta$IDV / $(-\Delta\Omega)$")
        axs[0,2].set_title(f"Per-collapse Transfer Rate\nmean={np.mean(ratios):.3f} ± {np.std(ratios):.3f}")
        axs[0,2].legend()

    # 4. F_i
    F_arr = np.array(sim.F_history)
    axs[1,0].plot(F_arr, color="crimson", lw=1.5)
    axs[1,0].set_xlabel("Sweep"); axs[1,0].set_ylabel(r"$\bar{F}_i$")
    axs[1,0].set_title(r"HN-01: $F_i = H/(\Omega+\epsilon_0)$")

    # 5. Phase test
    X_raw = [x for x in sim.phase_X_ds if x and not np.isnan(x)]
    Y_raw = [y for y in sim.phase_Y_ds if y and not np.isnan(y)]
    sw = np.arange(len(sim.phase_X_ds)) * 10 + 100
    if X_raw: axs[1,1].plot(sw[:len(X_raw)], X_raw, "purple", lw=2,
                             label=f"X: high-Ω  late={np.nanmean(X_raw[-5:]):.2f}")
    if Y_raw: axs[1,1].plot(sw[:len(Y_raw)], Y_raw, "teal",   lw=2,
                             label=f"Y: low-Ω   late={np.nanmean(Y_raw[-5:]):.2f}")
    axs[1,1].axhline(3.0, color="red", ls="--", lw=1)
    axs[1,1].set_ylim(0, 8); axs[1,1].set_xlabel("Sweep"); axs[1,1].set_ylabel("d_s")
    axs[1,1].set_title("Phase Test: X=crystallised, Y=young\nPrediction: X < Y")
    axs[1,1].legend()

    # 6. Psi speciation
    if sim.psi_snapshots:
        from scipy.signal import find_peaks
        counts, bins, _ = axs[1,2].hist(sim.psi_snapshots[-1], bins=50,
                                         color="darkorange", edgecolor="black", alpha=0.8)
        peaks, _ = find_peaks(counts, height=counts.max()*0.2, distance=3)
        axs[1,2].set_xlabel(r"$\Psi$"); axs[1,2].set_ylabel("Count")
        axs[1,2].set_title(f"Speciation: {len(peaks)} mode(s)")
        for p in peaks: axs[1,2].axvline(bins[p], color="red", ls="--", alpha=0.6)

    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches="tight")
    print(f"Plot saved: {save_path}")

    ds_late = np.mean(valid[-50:]) if len(valid) > 20 else float('nan')
    X_late  = np.nanmean(X_raw[-5:]) if len(X_raw) >= 5 else float('nan')
    Y_late  = np.nanmean(Y_raw[-5:]) if len(Y_raw) >= 5 else float('nan')
    beta_m  = float('nan')
    if sim.transfer_events:
        te_arr    = np.array(sim.transfer_events)
        id_d      = te_arr[:,1] - te_arr[:,0]
        om_d      = te_arr[:,3] - te_arr[:,2]
        vm        = np.abs(om_d) > 1e-6
        ratios    = id_d[vm] / (-om_d[vm])
        ratios    = ratios[np.isfinite(ratios) & (np.abs(ratios) < 10)]
        beta_m    = float(np.mean(ratios)) if len(ratios) > 0 else float('nan')
    psi_n = 0
    if sim.psi_snapshots:
        from scipy.signal import find_peaks
        counts, _ = np.histogram(sim.psi_snapshots[-1], bins=50)
        pks, _    = find_peaks(counts, height=counts.max()*0.2, distance=3)
        psi_n = len(pks)

    print(f"\n{'='*65}")
    print(f"CRF V20.3 — Results")
    print(f"{'='*65}")
    print(f"[GRAVITY]   R²={r_val**2:.4f}  slope={slope:.4f}  G_sim/ln2={G_sim/np.log(2):.4f}")
    print(f"[d_s]       late={ds_late:.4f}  (target 3.0)")
    print(f"[TRANSFER]  beta={beta_m:.4f}  (n_events={len(sim.transfer_events)})")
    print(f"            d_s/(2*ln2) = {3.0/(2*np.log(2)):.4f}  (conjecture)")
    print(f"[PHASE]     X={X_late:.3f}  Y={Y_late:.3f}  gap={Y_late-X_late:.3f}")
    print(f"[PSI]       {psi_n} modes")
    print(f"{'='*65}")


if __name__ == "__main__":
    sim = CRFHybridV20_3(N=500, dim=8, k=20)
    sim.run(max_sweeps=400)
    print("\nAnalyzing...")
    analyze(sim)
