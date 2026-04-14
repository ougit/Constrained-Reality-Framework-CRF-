import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.stats import linregress
import warnings
warnings.filterwarnings("ignore")

# =========================================================
# CRF Hybrid V20.5
# Adds GEOMETRY-LEVEL crystallisation tracking:
#   (AI suggestion confirmed: node-level was already tracked,
#    geometry-level lock was the missing layer)
#
# NEW: N_phase2 timeline = count(M > 1.3) per sweep
# NEW: geom_lock_event detection (N_phase2 >= Ncrit=74 AND d_s in [2.8,3.2])
# NEW: HN-04 irreversibility test (N_phase2 never drops below Ncrit after lock)
# NEW: tau_first_lock = sweep of first sustained geometry lock
# NEW: d_s estimator upgraded to n_trials=16, ~25 walkers => N_walk≈400
#      fixes d_s oscillation: N_walk >> N_phase2 => voting noise suppressed
#
# Ncrit = fII_crit * N = 0.147 * 500 = 74 (CRF_ThreePhase_v2)
# "Space is statistical consensus of ~Ncrit delta-Spark firing histories"
# =========================================================
# Builds on V20.3 with three new instrumentation layers
# targeting Path A, B, C from CRF master pattern analysis:
#
# NEW 1: Crystallised-node filter on transfer events (Path A)
#   V20.3: records ALL R-events (young + crystallised mixed)
#   V20.4: tags each event with node mass tier:
#          YOUNG (M < 1.3), MID (1.3-2.0), CRYST (M > 2.0)
#          -> H_before, H_after, T_inter, f12 components
#          -> per-tier beta table
#          -> closes f12 gap: checks if H_before->0 at high mass
#
# NEW 2: Psi-field (|ΔΨ|) derivation probe (Path B)
#   V20.3: psi_grad is computed but not linked to Kuramoto coupling
#   V20.4: records (psi_grad, phi_var, KL_mean, mass) per event
#          -> correlation: psi_grad vs KL_mean (expect linear)
#          -> fit: psi_grad = a * KL_mean + b (derive a,b from delta-chain)
#          -> if a ~ 1/D0 this closes |ΔΨ| derivation
#
# NEW 3: d_s oscillation analysis (Path C)
#   V20.3: ds_history stored but no oscillation analysis
#   V20.4: FFT of ds_history after burn-in
#          -> dominant frequency, amplitude, damping trend
#          -> compares amplitude vs eps0 prediction
#          -> theoretical note: oscillation = Heisenberg floor
#
# Results from V20.3 (inherited baseline):
#   d_s:  3.031 ± 0.076  gap: 0.980 ± 0.240  beta: -2.212 ± 0.015
#   R2:   0.9071 ± 0.0010   Psi: 7-9 modes
# =========================================================

class CRFHybridV20_5:

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

        # V20.3 logs (inherited)
        self.gravity_logs    = []
        self.ds_history      = []
        self.r_history       = []
        self.idv_history     = []
        self.omega_history   = []
        self.F_history       = []
        self.transfer_events = []  # V20.3: (IDV_before, IDV_after, Omega_before, Omega_after)
        self.phase_X_ds      = []
        self.phase_Y_ds      = []

        # NEW 1: Crystallised-tier event log (Path A — f12 gap)
        # Each entry: (H_before, H_after, phi_var, psi_grad, mass_M,
        #              T_inter, f12_measured, beta_event, tier)
        # tier: 0=young(M<1.3), 1=mid(1.3-2.0), 2=cryst(M>2.0)
        self.tier_events     = []
        self.last_fire_sweep = np.zeros(N, dtype=int)  # for T_inter

        # NEW 2: Psi-field probe (Path B — |ΔΨ| derivation)
        # Each entry: (psi_grad_i, phi_var_i, kl_mean_i, mass_i, H_before_i)
        self.psi_probe       = []

        # NEW 3: d_s oscillation tracking (Path C)
        self.sweep_counter   = 0  # global sweep index for T_inter

        # V20.5: geometry-level crystallisation tracking
        self.Ncrit            = int(0.147 * N)    # = 74 for N=500
        self.n_phase2_history = []                # N_phase2 per sweep
        self.geom_lock_events = []                # sweep indices of geometry locks
        self.tau_first_lock   = None              # first sustained lock sweep
        self._lock_streak     = 0                 # consecutive lock sweeps counter
        self._geom_locked     = False             # irreversibility flag
        self.irreversibility_violations = 0       # HN-04 test
        self.psi_snapshots   = []

        # NEW 3 storage: kept in ds_history, analyzed post-run

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
    def _estimate_ds(self, idx, n_trials=16):
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
        self.sweep_counter = sweep_idx
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
                # V20.3: record before
                idv_before = float(V_int[i])
                om_before  = float(Omega[i])
                H_before_i = float(H_P[i])
                mass_i     = float(self.node_mass[i])
                phi_var_i  = float(phi_var[i])
                psi_grad_i = float(psi_grad[i])

                # NEW 2: Psi-field probe — before firing
                kl_nb_mean = float(np.mean(KL[i, idx[i]]))
                self.psi_probe.append((psi_grad_i, phi_var_i,
                                       kl_nb_mean, mass_i, H_before_i))

                self.P[i] = self._born_resolve(i, idx[i])
                self._metric_leap(i, idx[i], KL)

                # NEW 1: T_inter measurement
                T_inter = sweep_idx - self.last_fire_sweep[i]
                self.last_fire_sweep[i] = sweep_idx

                self.local_time[i] += 1
                r_ev += 1

                # V20.3: compute after
                hp_new      = -np.sum(self.P[i] * np.log(self.P[i] + self.EPS))
                mass_new    = 1.0 + self.local_time[i] * self.kappa
                om_after    = mass_new - 1.0
                idv_after   = (hp_new
                               * (1.0 + phi_var_i)
                               * (1.0 + psi_grad_i)
                               * np.log1p(mass_new))
                self.transfer_events.append(
                    (idv_before, idv_after, om_before, om_after))

                # NEW 1: Tier-tagged event (Path A)
                if mass_i < 1.3:
                    tier = 0  # young
                elif mass_i < 2.0:
                    tier = 1  # mid
                else:
                    tier = 2  # crystallised

                om_d = om_after - om_before
                if abs(om_d) > 1e-6:
                    beta_ev = (idv_after - idv_before) / (-om_d)
                else:
                    beta_ev = float('nan')

                f12_meas = (1.0 + phi_var_i) * (1.0 + psi_grad_i)

                self.tier_events.append((
                    H_before_i,          # 0: H_before
                    float(hp_new),       # 1: H_after
                    phi_var_i,           # 2: phi_var
                    psi_grad_i,          # 3: psi_grad
                    mass_i,              # 4: mass M before
                    float(T_inter),      # 5: T_inter (sweeps)
                    f12_meas,            # 6: f12 = (1+phi_var)(1+psi_grad)
                    beta_ev,             # 7: per-event beta
                    tier                 # 8: 0/1/2
                ))

        if sweep_idx > 0 and sweep_idx % 10 == 0:
            self._sindy_prune()

        # V20.5: geometry-level crystallisation tracking
        n_phase2 = int(np.sum(self.node_mass > 1.3))
        self.n_phase2_history.append(n_phase2)

        t_e      = float(np.mean(self.local_time))
        max_mass = float(np.max(self.node_mass))

        ds = self._estimate_ds(idx)
        self.ds_history.append(ds)
        self.r_history.append(r_ev)

        # Geometry lock detection (after ds computed)
        if not np.isnan(ds):
            in_lock_zone = (n_phase2 >= self.Ncrit) and (2.8 <= ds <= 3.2)
            if in_lock_zone:
                self._lock_streak += 1
                if self._lock_streak >= 10 and self.tau_first_lock is None:
                    self.tau_first_lock = sweep_idx
                    self._geom_locked = True
                if self._lock_streak >= 5:
                    self.geom_lock_events.append(sweep_idx)
            else:
                if self._geom_locked and n_phase2 < self.Ncrit:
                    self.irreversibility_violations += 1
                self._lock_streak = 0

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
        print(f"CRF Hybrid V20.5  N={self.N}  lam_omega={self.lam_omega}")
        print(f"New: geometry crystallisation | Ncrit={self.Ncrit} | n_trials=16")
        print("-" * 72)
        for s in range(max_sweeps):
            t_e, r_ev, ds, mass, trig = self.sweep(s)
            if s % 25 == 0:
                ds_str = f"{ds:6.3f}" if not np.isnan(ds) else "   NaN"
                om_str = f"{np.mean(self.node_mass-1):.3f}"
                tag    = "  G" if trig else ""
                print(f"sweep {s:3d} | t={t_e:5.2f} | R={r_ev:4d} | "
                      f"d_s={ds_str} | Omega={om_str}{tag}")


def analyze_v204(sim, save_path="/mnt/user-data/outputs/CRF_V20_4_results.png"):
    import numpy as np
    from scipy.stats import linregress
    from scipy.signal import find_peaks

    fig, axs = plt.subplots(3, 3, figsize=(18, 15))
    fig.suptitle("CRF Hybrid V20.4 — Paths A/B/C Instrumentation", fontsize=13)

    # ── Row 0: inherited V20.3 diagnostics ──────────────────────────────

    # [0,0] Gravity
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
        axs[0,0].set_title(f"Gravity  R²={r_val**2:.4f}")
        axs[0,0].legend(fontsize=8)

    # [0,1] d_s history + oscillation (Path C)
    ds_arr = np.array(sim.ds_history)
    valid  = ds_arr[~np.isnan(ds_arr)]
    axs[0,1].plot(ds_arr, color="steelblue", alpha=0.7, lw=1)
    axs[0,1].axhline(3.0, color="red", ls="--", lw=1.5, label="target 3")
    osc_period = osc_amp = osc_trend = float('nan')
    if len(valid) > 80:
        late_ds = valid[len(valid)//2:]          # second half only
        ds_late_mean = np.mean(late_ds)
        axs[0,1].axhline(ds_late_mean, color="orange", ls=":",
                          label=f"late={ds_late_mean:.3f}")
        # PATH C: FFT
        detrended = late_ds - np.mean(late_ds)
        fft_mag   = np.abs(np.fft.rfft(detrended))
        freqs     = np.fft.rfftfreq(len(detrended))
        fft_mag[0] = 0   # remove DC
        peak_freq_idx = np.argmax(fft_mag)
        if freqs[peak_freq_idx] > 0:
            osc_period = 1.0 / freqs[peak_freq_idx]
            osc_amp    = 2.0 * fft_mag[peak_freq_idx] / len(detrended)
            # trend: is amplitude growing or shrinking?
            half = len(late_ds) // 2
            amp_early = np.std(late_ds[:half])
            amp_late  = np.std(late_ds[half:])
            osc_trend = amp_late - amp_early
        axs[0,1].set_title(f"d_s  period~{osc_period:.0f}sw  amp={osc_amp:.4f}\n"
                            f"trend={osc_trend:+.4f} (−=damping, +=growing)")
    else:
        axs[0,1].set_title(f"d_s  (need >80 valid pts for FFT)")
    axs[0,1].set_ylim(0, 8); axs[0,1].set_xlabel("Sweep"); axs[0,1].set_ylabel("d_s")
    axs[0,1].legend(fontsize=8)

    # [0,2] F_i (HN-01)
    F_arr = np.array(sim.F_history)
    axs[0,2].plot(F_arr, color="crimson", lw=1.5)
    axs[0,2].set_xlabel("Sweep"); axs[0,2].set_ylabel(r"$\bar{F}_i$")
    axs[0,2].set_title(r"HN-01: $F_i = H/(\Omega+\epsilon_0)$")

    # ── Row 1: Path A — crystallised-tier beta table ─────────────────────

    tier_names  = ["Young (M<1.3)", "Mid (1.3-2.0)", "Crystallised (M>2.0)"]
    tier_colors = ["steelblue", "darkorange", "purple"]
    beta_by_tier  = [[], [], []]
    H_before_tier = [[], [], []]
    H_after_tier  = [[], [], []]
    f12_tier      = [[], [], []]
    T_inter_tier  = [[], [], []]

    if sim.tier_events:
        te = np.array(sim.tier_events, dtype=object)
        for row in te:
            t = int(row[8])
            beta_ev = float(row[7])
            if np.isfinite(beta_ev) and abs(beta_ev) < 15:
                beta_by_tier[t].append(beta_ev)
            H_before_tier[t].append(float(row[0]))
            H_after_tier[t].append(float(row[1]))
            f12_tier[t].append(float(row[6]))
            T_int_val = float(row[5])
            if T_int_val > 0:
                T_inter_tier[t].append(T_int_val)

    # [1,0] Per-tier beta distributions
    for t in range(3):
        if beta_by_tier[t]:
            axs[1,0].hist(beta_by_tier[t], bins=40, alpha=0.5,
                          label=f"{tier_names[t]}: β={np.mean(beta_by_tier[t]):.3f}",
                          color=tier_colors[t])
    target_beta = 3.0 / (2 * np.log(2))
    axs[1,0].axvline(-target_beta, color="red", ls="--", lw=2,
                      label=f"d_s/(2ln2)={target_beta:.3f}")
    axs[1,0].set_xlabel(r"$\beta$ per event"); axs[1,0].set_ylabel("Count")
    axs[1,0].set_title("PATH A: β by mass tier")
    axs[1,0].legend(fontsize=7)

    # [1,1] H_before vs tier: is H_before → 0 at high mass?
    H_b_means = [np.mean(H_before_tier[t]) if H_before_tier[t] else float('nan')
                 for t in range(3)]
    H_a_means = [np.mean(H_after_tier[t])  if H_after_tier[t] else float('nan')
                 for t in range(3)]
    x = np.arange(3)
    w = 0.35
    axs[1,1].bar(x - w/2, H_b_means, w, label="H_before", color="steelblue", alpha=0.8)
    axs[1,1].bar(x + w/2, H_a_means, w, label="H_after",  color="darkorange", alpha=0.8)
    axs[1,1].set_xticks(x); axs[1,1].set_xticklabels(["Young","Mid","Cryst"], fontsize=8)
    axs[1,1].set_ylabel("Entropy H")
    # Prediction: H_before(cryst) → 0
    axs[1,1].axhline(0, color="red", ls="--", lw=1, label="H_before→0 prediction")
    axs[1,1].set_title("PATH A: H_before / H_after by tier\n(Prediction: H_before↓ as M↑)")
    axs[1,1].legend(fontsize=8)

    # [1,2] T_inter vs tier (confirms crystallised patience)
    T_means = [np.mean(T_inter_tier[t]) if T_inter_tier[t] else float('nan')
               for t in range(3)]
    axs[1,2].bar(["Young","Mid","Cryst"], T_means,
                  color=tier_colors, alpha=0.8)
    for i, v in enumerate(T_means):
        if np.isfinite(v):
            axs[1,2].text(i, v + 0.3, f"{v:.1f}", ha="center", fontsize=9)
    axs[1,2].set_ylabel("Mean T_inter (sweeps)")
    axs[1,2].set_title("PATH A: T_inter by tier\n(CRF_21a_Closure: cryst=38.6sw)")
    axs[1,2].axhline(38.6, color="red", ls="--", lw=1.5, label="21a: 38.6sw")
    axs[1,2].legend(fontsize=8)

    # ── Row 2: Path B (Psi probe) + Path C (FFT) + summary table ────────

    # [2,0] psi_grad vs KL_mean scatter — Path B
    if sim.psi_probe:
        pp = np.array(sim.psi_probe)
        psi_g  = pp[:, 0]    # psi_grad
        kl_m   = pp[:, 2]    # KL_mean
        mass_p = pp[:, 3]

        # Subsample for visibility
        idx_sub = np.random.choice(len(psi_g), size=min(2000, len(psi_g)), replace=False)
        sc2 = axs[2,0].scatter(kl_m[idx_sub], psi_g[idx_sub],
                                c=mass_p[idx_sub], cmap="plasma",
                                s=4, alpha=0.4)
        plt.colorbar(sc2, ax=axs[2,0], label="mass M")

        # Linear fit: psi_grad = a * KL_mean + b
        if len(kl_m) > 20:
            fit_slope, fit_intercept, fit_r, _, _ = linregress(kl_m, psi_g)
            x_line = np.linspace(kl_m.min(), kl_m.max(), 50)
            axs[2,0].plot(x_line, fit_slope * x_line + fit_intercept,
                          "r-", lw=2,
                          label=f"fit: a={fit_slope:.3f}  R²={fit_r**2:.3f}")
            # CRF prediction: a ≈ 1/D0
            pred_slope = 1.0 / sim.D0
            axs[2,0].plot(x_line, pred_slope * x_line,
                          "g--", lw=1.5,
                          label=f"CRF pred: 1/D0={pred_slope:.3f}")
        axs[2,0].set_xlabel("KL_mean"); axs[2,0].set_ylabel("|ΔΨ| (psi_grad)")
        axs[2,0].set_title("PATH B: psi_grad vs KL_mean\n(if a≈1/D0 → |ΔΨ| derived)")
        axs[2,0].legend(fontsize=7)

    # [2,1] f12 vs mass (Path A+B combined)
    if sim.tier_events:
        te = np.array(sim.tier_events, dtype=float)
        m_all  = te[:, 4]
        f12_all = te[:, 6]
        axs[2,1].scatter(m_all, f12_all, s=3, alpha=0.2, color="purple")
        # Binned mean
        bins = np.linspace(m_all.min(), m_all.max(), 20)
        bin_mid = 0.5 * (bins[:-1] + bins[1:])
        bin_f12 = [np.mean(f12_all[(m_all >= bins[b]) & (m_all < bins[b+1])])
                   for b in range(len(bins)-1)]
        axs[2,1].plot(bin_mid, bin_f12, "r-", lw=2, label="binned mean")
        axs[2,1].axhline(1.527, color="green", ls="--", lw=1.5,
                          label="f12=1.527 (21a)")
        axs[2,1].axhline(3.0/2.0, color="orange", ls=":", lw=1.5,
                          label="f12=d_s/2=1.5")
        axs[2,1].set_xlabel("mass M"); axs[2,1].set_ylabel("f12")
        axs[2,1].set_title("PATH A+B: f12 vs mass\n(Kuramoto pred: f12=d_s/2)")
        axs[2,1].legend(fontsize=7)

    # [2,2] Path C: d_s FFT power spectrum
    if len(valid) > 80:
        late_ds   = valid[len(valid)//2:]
        detrended = late_ds - np.mean(late_ds)
        fft_mag   = np.abs(np.fft.rfft(detrended))
        freqs     = np.fft.rfftfreq(len(detrended))
        fft_mag[0] = 0
        axs[2,2].plot(freqs, fft_mag, color="teal", lw=1.5)
        if freqs[np.argmax(fft_mag)] > 0:
            axs[2,2].axvline(freqs[np.argmax(fft_mag)], color="red", ls="--",
                              label=f"peak f={freqs[np.argmax(fft_mag)]:.4f}\n"
                                    f"T={1/freqs[np.argmax(fft_mag)]:.0f}sw")
        # eps0 prediction: expected oscillation frequency ~ alpha * eps0
        pred_f = sim.alpha * sim.eps0
        axs[2,2].axvline(pred_f, color="orange", ls=":",
                          label=f"ε0·ln2={pred_f:.4f}")
        axs[2,2].set_xlabel("Frequency (1/sweep)")
        axs[2,2].set_ylabel("FFT magnitude")
        axs[2,2].set_title("PATH C: d_s oscillation spectrum\n(theory: Heisenberg floor)")
        axs[2,2].legend(fontsize=7)

    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches="tight")
    print(f"Plot saved: {save_path}")

    # ── Summary printout ─────────────────────────────────────────────────
    ds_arr = np.array(sim.ds_history); valid = ds_arr[~np.isnan(ds_arr)]
    ds_late = np.nanmean(valid[-50:]) if len(valid) > 20 else float('nan')

    beta_all = [b for tier in beta_by_tier for b in tier if np.isfinite(b)]
    beta_cryst = [b for b in beta_by_tier[2] if np.isfinite(b)]

    print(f"\n{'='*70}")
    print(f"CRF V20.4 — Results Summary")
    print(f"{'='*70}")
    print(f"[GRAVITY]   R²={r_val**2:.4f}  slope={slope:.4f}  G_sim/ln2={G_sim/np.log(2):.4f}")
    print(f"[d_s]       late={ds_late:.4f}  (target 3.0)")
    print(f"            oscillation period~{osc_period:.0f}sw  amp={osc_amp:.4f}  trend={osc_trend:+.4f}")
    print(f"            eps0*ln2 pred = {sim.alpha*sim.eps0:.4f}")
    print(f"")
    print(f"PATH A — f12 / tier beta:")
    for t in range(3):
        b_m  = np.mean(beta_by_tier[t]) if beta_by_tier[t] else float('nan')
        hb   = np.mean(H_before_tier[t]) if H_before_tier[t] else float('nan')
        ha   = np.mean(H_after_tier[t]) if H_after_tier[t] else float('nan')
        ti   = np.mean(T_inter_tier[t]) if T_inter_tier[t] else float('nan')
        f12v = np.mean(f12_tier[t]) if f12_tier[t] else float('nan')
        n    = len(beta_by_tier[t])
        print(f"  {tier_names[t]:22s}  β={b_m:+.3f}  H_b={hb:.3f}  H_a={ha:.3f}"
              f"  T={ti:.1f}sw  f12={f12v:.3f}  n={n}")
    print(f"  d_s/(2ln2) target     = {3.0/(2*np.log(2)):.3f}")
    print(f"  f12=d_s/2 (Kuramoto)  = {ds_late/2:.3f}")
    print(f"")
    print(f"PATH B — |ΔΨ| probe:")
    if sim.psi_probe and len(sim.psi_probe) > 20:
        pp = np.array(sim.psi_probe)
        fs, fi, fr, _, _ = linregress(pp[:,2], pp[:,0])
        print(f"  psi_grad = {fs:.4f}*KL_mean + {fi:.4f}  R²={fr**2:.4f}")
        print(f"  CRF pred: 1/D0 = {1.0/sim.D0:.4f}")
        gap_pct = abs(fs - 1.0/sim.D0) / (1.0/sim.D0) * 100
        print(f"  gap from 1/D0: {gap_pct:.1f}%")
    print(f"{'='*70}")

    return {
        'ds_late': ds_late, 'osc_period': osc_period, 'osc_amp': osc_amp,
        'osc_trend': osc_trend, 'beta_all': np.mean(beta_all) if beta_all else float('nan'),
        'beta_cryst': np.mean(beta_cryst) if beta_cryst else float('nan'),
        'T_cryst': np.mean(T_inter_tier[2]) if T_inter_tier[2] else float('nan'),
        'H_before_cryst': np.mean(H_before_tier[2]) if H_before_tier[2] else float('nan'),
    }


def analyze_v205(sim, save_path="/mnt/user-data/outputs/CRF_V20_5_results.png"):
    import numpy as np
    from scipy.stats import linregress
    from scipy.signal import find_peaks
    import matplotlib.pyplot as plt

    fig, axs = plt.subplots(3, 3, figsize=(18, 15))
    fig.suptitle("CRF Hybrid V20.5 — Geometry Crystallisation + d_s Lock", fontsize=13)

    # [0,0] Gravity
    logs = sim.gravity_logs
    slope = intercept = r_val = 0; G_sim = 0
    if logs:
        ta, ca, t_all = [], [], []
        for e in logs:
            for t, c in e["pairs"]: ta.append(t); ca.append(c); t_all.append(e["time"])
        theo = np.array(ta); crf = np.array(ca)
        sc = axs[0,0].scatter(theo, crf, c=t_all, cmap="viridis", alpha=0.3, s=3)
        slope, intercept, r_val, _, _ = linregress(np.log10(theo), np.log10(crf))
        G_sim = 10**intercept
        x_fit = np.sort(theo)
        axs[0,0].plot(x_fit, G_sim*x_fit**slope, "r--", lw=2, label=f"R²={r_val**2:.4f}")
        axs[0,0].set_xscale("log"); axs[0,0].set_yscale("log")
        axs[0,0].set_title(f"Gravity R²={r_val**2:.4f}")
        axs[0,0].legend(fontsize=8)

    # [0,1] d_s history with lock events
    ds_arr = np.array(sim.ds_history)
    valid  = ds_arr[~np.isnan(ds_arr)]
    axs[0,1].plot(ds_arr, color="steelblue", alpha=0.7, lw=1)
    axs[0,1].axhline(3.0, color="red", ls="--", lw=1.5, label="target 3")
    axs[0,1].axhline(2.8, color="orange", ls=":", lw=1, label="lock zone")
    axs[0,1].axhline(3.2, color="orange", ls=":", lw=1)
    if sim.tau_first_lock:
        axs[0,1].axvline(sim.tau_first_lock, color="green", lw=2,
                          label=f"1st lock: sw{sim.tau_first_lock}")
    if len(valid) > 20:
        late = np.nanmean(valid[-50:])
        axs[0,1].axhline(late, color="purple", ls=":", label=f"late={late:.3f}")
    axs[0,1].set_ylim(0, 8); axs[0,1].set_xlabel("Sweep"); axs[0,1].set_ylabel("d_s")
    axs[0,1].set_title(f"d_s (n_trials=16)  HN-04 violations={sim.irreversibility_violations}")
    axs[0,1].legend(fontsize=7)

    # [0,2] N_phase2 timeline vs Ncrit
    if sim.n_phase2_history:
        axs[0,2].plot(sim.n_phase2_history, color="teal", lw=1.5)
        axs[0,2].axhline(sim.Ncrit, color="red", ls="--", lw=2,
                          label=f"Ncrit={sim.Ncrit}")
        if sim.tau_first_lock:
            axs[0,2].axvline(sim.tau_first_lock, color="green", lw=2,
                              label=f"geom lock sw{sim.tau_first_lock}")
        axs[0,2].set_xlabel("Sweep"); axs[0,2].set_ylabel("N_phase2 (M>1.3)")
        axs[0,2].set_title(f"Geometry crystallisation\n(CRF_ThreePhase Ncrit={sim.Ncrit})")
        axs[0,2].legend(fontsize=8)

    # [1,0-2] Path A tier analysis (inherited)
    tier_names  = ["Young (M<1.3)", "Mid (1.3-2.0)", "Cryst (M>2.0)"]
    tier_colors = ["steelblue", "darkorange", "purple"]
    beta_by_tier = [[], [], []]
    H_before_tier = [[], [], []]
    T_inter_tier  = [[], [], []]
    if sim.tier_events:
        te = np.array(sim.tier_events, dtype=object)
        for row in te:
            t = int(row[8])
            bv = float(row[7])
            if np.isfinite(bv) and abs(bv) < 15:
                beta_by_tier[t].append(bv)
            H_before_tier[t].append(float(row[0]))
            tv = float(row[5])
            if tv > 0: T_inter_tier[t].append(tv)

    for t in range(3):
        if beta_by_tier[t]:
            axs[1,0].hist(beta_by_tier[t], bins=40, alpha=0.5,
                          label=f"{tier_names[t]}: β={np.mean(beta_by_tier[t]):.3f}",
                          color=tier_colors[t])
    axs[1,0].axvline(-3/(2*np.log(2)), color="red", ls="--", lw=2,
                      label=f"d_s/(2ln2)={3/(2*np.log(2)):.3f}")
    axs[1,0].set_title("PATH A: β by mass tier"); axs[1,0].legend(fontsize=7)

    T_means = [np.mean(T_inter_tier[t]) if T_inter_tier[t] else float("nan") for t in range(3)]
    axs[1,1].bar(["Young","Mid","Cryst"], T_means, color=tier_colors, alpha=0.8)
    for i, v in enumerate(T_means):
        if np.isfinite(v): axs[1,1].text(i, v+0.5, f"{v:.1f}", ha="center", fontsize=9)
    axs[1,1].axhline(38.6, color="red", ls="--", lw=1.5, label="21a: 38.6sw")
    axs[1,1].set_title("T_inter by tier"); axs[1,1].legend(fontsize=8)

    H_b = [np.mean(H_before_tier[t]) if H_before_tier[t] else float("nan") for t in range(3)]
    axs[1,2].bar(["Young","Mid","Cryst"], H_b, color=tier_colors, alpha=0.8)
    axs[1,2].set_title("H_before by tier"); axs[1,2].set_ylabel("Entropy")

    # [2,0] d_s FFT
    if len(valid) > 80:
        late_ds = valid[len(valid)//2:]
        detrended = late_ds - np.mean(late_ds)
        fft_mag = np.abs(np.fft.rfft(detrended))
        freqs = np.fft.rfftfreq(len(detrended)); fft_mag[0]=0
        axs[2,0].plot(freqs, fft_mag, color="teal", lw=1.5)
        pk = np.argmax(fft_mag)
        if freqs[pk] > 0:
            axs[2,0].axvline(freqs[pk], color="red", ls="--",
                              label=f"T={1/freqs[pk]:.0f}sw")
        axs[2,0].set_title("d_s FFT (n_trials=16 vs 8)")
        axs[2,0].legend(fontsize=8)

    # [2,1] Geom lock events density
    if sim.geom_lock_events:
        axs[2,1].plot(sim.geom_lock_events,
                       [1]*len(sim.geom_lock_events), "|",
                       color="green", markersize=8, alpha=0.5)
        axs[2,1].set_xlabel("Sweep")
        axs[2,1].set_title(f"Geometry lock events (n={len(sim.geom_lock_events)})")
        lock_frac = len(sim.geom_lock_events)/max(1, len(sim.ds_history))
        axs[2,1].text(0.05, 0.8, f"Lock fraction: {lock_frac:.2f}",
                       transform=axs[2,1].transAxes, fontsize=11)

    # [2,2] N_phase2 vs ds scatter
    if sim.n_phase2_history and len(sim.ds_history) == len(sim.n_phase2_history):
        ds_c = ds_arr[:len(sim.n_phase2_history)]
        n2_c = np.array(sim.n_phase2_history)
        valid_m = ~np.isnan(ds_c)
        axs[2,2].scatter(n2_c[valid_m], ds_c[valid_m], s=3, alpha=0.3, color="purple")
        axs[2,2].axhline(3.0, color="red", ls="--", lw=1, label="d_s=3")
        axs[2,2].axvline(sim.Ncrit, color="orange", ls="--", lw=1.5,
                          label=f"Ncrit={sim.Ncrit}")
        axs[2,2].set_xlabel("N_phase2"); axs[2,2].set_ylabel("d_s")
        axs[2,2].set_title("d_s vs N_phase2 (geometry vote)")
        axs[2,2].legend(fontsize=8)

    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches="tight")
    print(f"Plot saved: {save_path}")

    ds_late = np.nanmean(valid[-50:]) if len(valid) > 20 else float("nan")
    beta_all = [b for tier in beta_by_tier for b in tier if np.isfinite(b)]
    print(f"\n{'='*65}")
    print(f"CRF V20.5 — Results")
    print(f"{'='*65}")
    print(f"[GRAVITY]   R²={r_val**2:.4f}  slope={slope:.4f}")
    print(f"[d_s]       late={ds_late:.4f}  (n_trials=16)")
    print(f"[GEOM LOCK] tau_first={sim.tau_first_lock}  events={len(sim.geom_lock_events)}")
    print(f"            HN-04 violations={sim.irreversibility_violations}")
    print(f"            Ncrit={sim.Ncrit}  final N_phase2={sim.n_phase2_history[-1] if sim.n_phase2_history else 0}")
    print(f"[BETA]      global={np.mean(beta_all):.4f}  d_s/(2ln2)={3/(2*0.6931):.4f}")
    print(f"{'='*65}")


if __name__ == "__main__":
    sim = CRFHybridV20_5(N=500, dim=8, k=20)
    sim.run(max_sweeps=600)
    print("\nAnalyzing...")
    analyze_v205(sim)

