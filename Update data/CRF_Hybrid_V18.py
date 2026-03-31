import numpy as np
from itertools import combinations
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.stats import linregress
import warnings
warnings.filterwarnings("ignore")

# =========================================================
# CRF Hybrid V18 — IDV Paper Simulator
#
# Extends V17 with three targeted tests:
#
# TEST 1: Marble Effect
#   Split nodes into Group X (top 20% IDV) and Group Y (bottom 20%)
#   Measure: does high-IDV group achieve d_s -> 3 faster?
#   Prediction: X reaches d_s < 3.5 before Y does
#
# TEST 2: IDI Formal Measurement
#   V_int grows while d_s stays near 3
#   Track: correlation(IDV_rate, d_s_variance) should be negative
#
# TEST 3: Speciation
#   Psi histogram should show distinct modes (not single Gaussian)
#   Measure: number of peaks in Psi distribution over time
#
# Changes from V17:
#   lam_idv: 0.002 -> 0.005  (stronger IDV-metric coupling)
#   sigma:   0.5   -> 0.3    (stricter speciation)
#   Added: per-group d_s tracking for Marble Effect
# =========================================================

class CRFHybridV18:

    def __init__(self, N=500, dim=8, k=20):
        self.N   = N
        self.dim = dim
        self.k   = k
        self.EPS = 1e-8

        # ---- CRF constants ----
        self.alpha   = np.log(2)
        self.I_eff   = 0.7007
        self.eps0    = abs(self.I_eff - self.alpha)
        self.D0      = 0.9403
        self.kappa   = 0.15
        self.SINDY_T = 0.02
        self.sigma   = 0.3    # stricter Psi speciation (V17: 0.5)
        self.lam_idv = 0.005  # stronger IDV coupling (V17: 0.002)

        # ---- States ----
        self.P          = self._init_P()
        self.X          = self._init_X()
        self._add_spatial_bias()
        self.metric     = [np.eye(dim) for _ in range(N)]
        self.local_time = np.zeros(N)
        self.node_mass  = np.ones(N)
        self.Phi        = np.random.rand(N) * 2 * np.pi
        self.Psi        = np.random.randn(N) * 0.1

        # ---- Standard logs ----
        self.gravity_logs  = []
        self.ds_history    = []
        self.theta_history = []
        self.r_history     = []
        self.idv_history   = []
        self.dint_history  = []
        self.psi_snapshots = []

        # ---- Marble Effect logs ----
        # Track d_s separately for high-IDV (X) and low-IDV (Y) groups
        self.marble_X_ds   = []   # d_s of top-20% IDV nodes
        self.marble_Y_ds   = []   # d_s of bottom-20% IDV nodes
        self.marble_X_idv  = []   # mean IDV of X group
        self.marble_Y_idv  = []   # mean IDV of Y group

        # ---- IDI logs ----
        self.idi_rate      = []   # dV_int/dt
        self.ds_variance   = []   # variance of d_s window

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

    # ---- Vectorized KL ----
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
        eta     = 0.05
        new_Phi = self.Phi.copy()
        for i in range(self.N):
            nb        = idx[i]
            new_Phi[i] += eta * np.mean(KL[i, nb] * np.sin(self.Phi[nb] - self.Phi[i]))
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
        return V_int, np.log1p(V_int)

    # ---- R-event mechanics ----
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

    def _born_resolve(self, i, idx_i):
        target  = np.mean(self.P[idx_i], axis=0)
        alpha_d = (target + self.eps0) / self.eps0
        return np.maximum(np.random.dirichlet(alpha_d), self.EPS)

    def _metric_leap(self, i, idx_i, KL, IDV_i):
        curv = np.zeros(self.dim)
        for j in idx_i:
            curv += KL[i, j] * (self.X[j] - self.X[i])
        curv /= self.k
        align = np.mean(self.X[idx_i], axis=0) - self.X[i]
        move  = 0.1 * curv + 0.05 * align + self.eps0 * np.random.randn(self.dim)
        self.X[i] += move
        G = self.metric[i] + 0.01 * np.outer(curv, curv)
        # IDV-driven 3D coupling (SO3 slice)
        for j in idx_i:
            r3    = (self.X[j] - self.X[i])[:3]
            cos_p = np.cos(self.Phi[j] - self.Phi[i])
            G[:3, :3] += self.lam_idv * IDV_i * cos_p * np.outer(r3, r3)
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
    def _measure_gravity(self, core_nodes, t_e):
        if len(core_nodes) < 2: return
        pairs     = []
        non_cores = [n for n in range(self.N) if n not in set(core_nodes)]
        extra     = (np.random.choice(non_cores, size=min(50, len(non_cores)),
                                      replace=False).tolist() if non_cores else [])
        for i in core_nodes:
            Omega_i = self.node_mass[i] - 1.0
            if Omega_i <= 0: continue
            for j in list(core_nodes) + extra:
                if i == j: continue
                Omega_j = self.node_mass[j] - 1.0
                if Omega_j <= 0: continue
                r_sq  = float(np.dot(self.X[i,:3]-self.X[j,:3],
                                     self.X[i,:3]-self.X[j,:3])) + self.EPS
                pairs.append(((self.node_mass[i]*self.node_mass[j])/r_sq,
                               (Omega_i*Omega_j)/r_sq))
        if pairs:
            self.gravity_logs.append({"time": t_e, "pairs": pairs})

    # ---- d_s estimator ----
    def _estimate_ds(self, idx):
        returns    = []
        walk_times = list(range(2, 20, 2))
        for wt in walk_times:
            hits = 0
            for start in range(0, self.N, 10):
                curr = start
                for _ in range(wt):
                    curr = int(idx[curr, np.random.randint(self.k)])
                if curr == start: hits += 1
            returns.append(max(hits / (self.N/10 + self.EPS), 1e-4))
        log_t = np.log(walk_times)
        log_p = np.log(returns)
        if np.std(log_p) < 0.25: return np.nan
        slope, _ = np.polyfit(log_t, log_p, 1)
        return -2.0 * slope

    # ---- Marble Effect: d_s per IDV group ----
    def _marble_test(self, V_int, idx):
        n_group = max(1, self.N // 5)   # 20%
        sorted_idv = np.argsort(V_int)
        group_X = sorted_idv[-n_group:].tolist()   # high IDV
        group_Y = sorted_idv[:n_group].tolist()    # low IDV

        # Build sub-idx for each group
        def ds_subgroup(nodes):
            n = len(nodes)
            if n < 10: return np.nan
            node_set = set(nodes)
            sub_idx  = []
            for i in nodes:
                nb_i = [j for j in idx[i] if j in node_set]
                if len(nb_i) < 2:
                    nb_i = list(idx[i])[:min(5, self.k)]
                sub_idx.append(nb_i)
            # random walk within sub-idx
            returns = []
            for wt in range(2, 14, 2):
                hits = 0
                samples = nodes[::max(1, len(nodes)//10)]
                for start in samples:
                    curr = nodes.index(start) if start in nodes else 0
                    for _ in range(wt):
                        nb_curr = sub_idx[curr]
                        next_j  = nb_curr[np.random.randint(len(nb_curr))]
                        if next_j in node_set:
                            curr = nodes.index(next_j)
                    if nodes[curr] == start: hits += 1
                p = hits / (len(samples) + self.EPS)
                returns.append(max(p, 1e-4))
            log_t = np.log(list(range(2, 14, 2)))
            log_p = np.log(returns)
            if np.std(log_p) < 0.2: return np.nan
            slope, _ = np.polyfit(log_t, log_p, 1)
            return -2.0 * slope

        ds_X = ds_subgroup(group_X)
        ds_Y = ds_subgroup(group_Y)
        self.marble_X_ds.append(ds_X)
        self.marble_Y_ds.append(ds_Y)
        self.marble_X_idv.append(float(np.mean(V_int[group_X])))
        self.marble_Y_idv.append(float(np.mean(V_int[group_Y])))

    def _detect_cores(self, n=50):
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
        V_int, d_int   = self._compute_idv(idx)

        # IDI rate (finite difference)
        if self.idv_history:
            self.idi_rate.append(float(np.mean(V_int)) - self.idv_history[-1])
        else:
            self.idi_rate.append(0.0)

        self.idv_history.append(float(np.mean(V_int)))
        self.dint_history.append(float(np.mean(d_int)))

        tension, threshold = self._compute_tension_threshold(KL, idx)
        r_ev = 0
        for i in range(self.N):
            if tension[i] > threshold[i]:
                self.P[i] = self._born_resolve(i, idx[i])
                self._metric_leap(i, idx[i], KL, float(V_int[i]))
                self.local_time[i] += 1
                r_ev += 1

        if sweep_idx > 0 and sweep_idx % 10 == 0:
            self._sindy_prune()

        t_e      = float(np.mean(self.local_time))
        max_mass = float(np.max(self.node_mass))
        th_mean  = float(np.mean(threshold))

        ds = self._estimate_ds(idx)
        self.ds_history.append(ds)
        self.theta_history.append(th_mean)
        self.r_history.append(r_ev)

        # d_s variance window (IDI test)
        window = [x for x in self.ds_history[-20:] if not np.isnan(x)]
        self.ds_variance.append(float(np.var(window)) if window else 0.0)

        # Marble Effect test every 10 sweeps
        if sweep_idx % 10 == 0:
            self._marble_test(V_int, idx)

        if sweep_idx % 50 == 0:
            self.psi_snapshots.append(self.Psi.copy())

        trigger = False
        if max_mass > 1.2:
            cores = self._detect_cores()
            if len(cores) >= 2:
                self._measure_gravity(cores, t_e)
                trigger = True

        return t_e, r_ev, ds, th_mean, max_mass, trigger, float(np.mean(V_int))

    def run(self, max_sweeps=400):
        print(f"CRF Hybrid V18  N={self.N}  lam={self.lam_idv}  sigma={self.sigma}")
        print(f"Tests: Marble Effect | IDI | Speciation | Gravity")
        print("-" * 72)
        for s in range(max_sweeps):
            t_e, r_ev, ds, th, mass, trig, idv_m = self.sweep(s)
            if s % 25 == 0:
                ds_str = f"{ds:6.3f}" if not np.isnan(ds) else "   NaN"
                tag    = "  G" if trig else ""
                print(f"sweep {s:3d} | t={t_e:5.2f} | R={r_ev:4d} | "
                      f"d_s={ds_str} | IDV={idv_m:.3f} | mass={mass:.2f}x{tag}")


# =====================================================
# Analytics — four plots for the IDV paper
# =====================================================
def analyze(sim, save_path="/mnt/user-data/outputs/CRF_V18_results.png"):
    fig, axs = plt.subplots(2, 3, figsize=(18, 10))
    fig.suptitle("CRF Hybrid V18 — IDV Paper: Marble Effect + IDI + Speciation",
                 fontsize=13)

    # 1. Gravity
    logs = sim.gravity_logs
    slope = intercept = r_val = 0
    G_sim = 0
    if logs:
        theo_all, crf_all, t_all = [], [], []
        for entry in logs:
            for theo, crf in entry["pairs"]:
                theo_all.append(theo); crf_all.append(crf)
                t_all.append(entry["time"])
        theo = np.array(theo_all); crf = np.array(crf_all)
        sc = axs[0,0].scatter(theo, crf, c=t_all, cmap="viridis", alpha=0.3, s=3)
        plt.colorbar(sc, ax=axs[0,0], label="time")
        slope, intercept, r_val, _, _ = linregress(np.log10(theo), np.log10(crf))
        G_sim = 10**intercept
        x_fit = np.sort(theo)
        axs[0,0].plot(x_fit, G_sim*x_fit**slope, "r--", lw=2,
                      label=f"slope={slope:.3f}  R²={r_val**2:.3f}")
        axs[0,0].set_xscale("log"); axs[0,0].set_yscale("log")
        axs[0,0].set_xlabel(r"$m_1m_2/r^2$")
        axs[0,0].set_ylabel(r"$\Omega_i\Omega_j/r^2$")
        axs[0,0].set_title(f"Gravity  R²={r_val**2:.3f}  G_sim={G_sim:.4f}")
        axs[0,0].legend()

    # 2. d_s + IDV (IDI test)
    ds_arr  = np.array(sim.ds_history)
    idv_arr = np.array(sim.idv_history)
    ax_ds   = axs[0,1]
    ax_ds.plot(ds_arr, color="steelblue", alpha=0.7, lw=1, label="d_s")
    ax_ds.axhline(3.0, color="red", ls="--", lw=1.5, label="target 3")
    valid = ds_arr[~np.isnan(ds_arr)]
    if len(valid) > 20:
        late = np.mean(valid[-50:])
        ax_ds.axhline(late, color="orange", ls=":", label=f"late={late:.2f}")
    ax_ds.set_ylim(0, 8)
    ax_ds.set_xlabel("Sweep"); ax_ds.set_ylabel("d_s", color="steelblue")
    ax_idv = ax_ds.twinx()
    ax_idv.plot(idv_arr, color="teal", alpha=0.7, lw=1.5, label=r"$\overline{V^{int}}$")
    ax_idv.set_ylabel(r"$\overline{V^{int}}$", color="teal")
    ax_ds.set_title("IDI: d_s stable while IDV inflates")
    ax_ds.legend(loc="upper right")

    # 3. Marble Effect
    X_ds  = np.array([x for x in sim.marble_X_ds if x is not None and not np.isnan(x)])
    Y_ds  = np.array([y for y in sim.marble_Y_ds if y is not None and not np.isnan(y)])
    X_idv = np.array(sim.marble_X_idv)
    Y_idv = np.array(sim.marble_Y_idv)
    sweeps_marble = np.arange(len(sim.marble_X_ds)) * 10
    sweeps_X = sweeps_marble[:len(X_ds)]
    sweeps_Y = sweeps_marble[:len(Y_ds)]
    if len(X_ds) > 0:
        axs[0,2].plot(sweeps_X, X_ds, color="purple", lw=2,
                      label=f"X (high IDV, mean={X_idv.mean():.2f})")
    if len(Y_ds) > 0:
        axs[0,2].plot(sweeps_Y, Y_ds, color="gray", lw=2, alpha=0.7,
                      label=f"Y (low IDV, mean={Y_idv.mean():.2f})")
    axs[0,2].axhline(3.0, color="red", ls="--", lw=1)
    axs[0,2].set_ylim(0, 8)
    axs[0,2].set_xlabel("Sweep"); axs[0,2].set_ylabel("d_s subgroup")
    axs[0,2].set_title("Marble Effect: high IDV -> d_s -> 3 faster?")
    axs[0,2].legend()

    # 4. IDI rate vs d_s variance
    idi_arr = np.array(sim.idi_rate)
    dsv_arr = np.array(sim.ds_variance)
    min_len = min(len(idi_arr), len(dsv_arr))
    axs[1,0].scatter(idi_arr[:min_len], dsv_arr[:min_len],
                     alpha=0.4, s=10, color="darkorange")
    axs[1,0].set_xlabel("IDI rate (dV_int/dt)")
    axs[1,0].set_ylabel("Var(d_s) [20-sweep window]")
    axs[1,0].set_title("IDI rate vs d_s variance\n(negative corr = IDI stabilizes d_s)")
    # Add correlation
    mask = np.isfinite(idi_arr[:min_len]) & np.isfinite(dsv_arr[:min_len])
    if mask.sum() > 10:
        corr = np.corrcoef(idi_arr[:min_len][mask], dsv_arr[:min_len][mask])[0,1]
        axs[1,0].set_title(f"IDI rate vs d_s variance  (r={corr:.3f})")

    # 5. Speciation (Psi final)
    if sim.psi_snapshots:
        psi_final = sim.psi_snapshots[-1]
        counts, bins, _ = axs[1,1].hist(psi_final, bins=40, color="darkorange",
                                         edgecolor="black", alpha=0.8)
        axs[1,1].set_xlabel(r"$\Psi$ (pattern mode)")
        axs[1,1].set_ylabel("Node count")
        # Count peaks
        from scipy.signal import find_peaks
        peaks, _ = find_peaks(counts, height=counts.max()*0.2, distance=3)
        axs[1,1].set_title(f"Speciation: {len(peaks)} distinct mode(s) detected")
        for p in peaks:
            axs[1,1].axvline(bins[p], color="red", ls="--", alpha=0.6)

    # 6. IDV vs d_s scatter (Marble Effect probe)
    min_len2 = min(len(idv_arr), len(ds_arr))
    ds_trim  = ds_arr[:min_len2]
    idv_trim = idv_arr[:min_len2]
    mask2 = ~np.isnan(ds_trim)
    axs[1,2].scatter(idv_trim[mask2], ds_trim[mask2],
                     alpha=0.4, s=8, color="steelblue")
    axs[1,2].axhline(3.0, color="red", ls="--", lw=1)
    axs[1,2].set_xlabel(r"$\overline{V^{int}}$")
    axs[1,2].set_ylabel("d_s")
    axs[1,2].set_title("IDV vs d_s\n(should stabilize near 3 as IDV grows)")

    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches="tight")
    print(f"Plot: {save_path}")

    # Summary
    ds_late = np.mean(valid[-50:]) if len(valid) > 20 else float('nan')
    # Marble: late-mean d_s for each group
    X_late = np.nanmean([x for x in sim.marble_X_ds[-20:] if x]) if sim.marble_X_ds else float('nan')
    Y_late = np.nanmean([y for y in sim.marble_Y_ds[-20:] if y]) if sim.marble_Y_ds else float('nan')
    # IDI: correlation
    mask3 = np.isfinite(idi_arr[:min_len]) & np.isfinite(dsv_arr[:min_len])
    idi_ds_corr = float(np.corrcoef(idi_arr[:min_len][mask3],
                                     dsv_arr[:min_len][mask3])[0,1]) if mask3.sum()>5 else float('nan')
    psi_peaks = 0
    if sim.psi_snapshots:
        from scipy.signal import find_peaks
        counts, _ = np.histogram(sim.psi_snapshots[-1], bins=40)
        peaks, _ = find_peaks(counts, height=counts.max()*0.2, distance=3)
        psi_peaks = len(peaks)

    print(f"\n{'='*62}")
    print(f"CRF V18 — IDV Paper Results")
    print(f"{'='*62}")
    print(f"[GRAVITY]")
    print(f"  R²             = {r_val**2:.4f}   (V16: 0.906)")
    print(f"  Slope          = {slope:.4f}   (target +1.0)")
    print(f"  G_sim / ln2    = {G_sim/np.log(2):.4f}")
    print(f"[IDI]")
    print(f"  IDV final mean = {idv_arr[-1]:.4f}")
    print(f"  d_s late mean  = {ds_late:.4f}   (target 3.0)")
    print(f"  IDI rate vs d_s_var corr = {idi_ds_corr:.4f}")
    print(f"  (negative = IDI stabilises d_s, confirms IDI)")
    print(f"[MARBLE EFFECT]")
    print(f"  Group X (high IDV) d_s late = {X_late:.4f}")
    print(f"  Group Y (low IDV)  d_s late = {Y_late:.4f}")
    print(f"  Gap X-Y = {X_late-Y_late:.4f}   (negative = X closer to 3)")
    print(f"[SPECIATION]")
    print(f"  Psi peaks detected = {psi_peaks}")
    print(f"  (>1 = distinct matter modes formed)")
    print(f"{'='*62}")


if __name__ == "__main__":
    sim = CRFHybridV18(N=500, dim=8, k=20)
    sim.run(max_sweeps=400)
    print("\nAnalyzing...")
    analyze(sim)
