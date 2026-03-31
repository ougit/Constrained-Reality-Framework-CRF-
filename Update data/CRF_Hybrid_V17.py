import numpy as np
from itertools import combinations
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.stats import linregress
import warnings
warnings.filterwarnings("ignore")

# =========================================================
# CRF Hybrid V17
# Extends V16 canonical base (R²=0.906, d_s=3.008) with:
#   Phi field   : wave layer  Phi_i <- DKL * sin(Phi_j - Phi_i)
#   Psi modes   : identity    Psi_i <- 0.9*Psi + 0.1*mean_nb + eps0*noise
#   IDV         : internal dimensional volume per node
#   IDV-metric  : G[:3,:3] += lambda * IDV * cos(Phi) * r3 outer r3
#
# Causal chain (all derived from delta-chain):
#   delta -> R-events -> N_eff -> mass -> Omega -> IDV
#   -> G[:3,:3] dominant -> d_s -> 3 (SO3 forces 3D)
#   -> neighbours inherit -> Marble Effect
# =========================================================

class CRFHybridV17:

    def __init__(self, N=500, dim=8, k=20):
        self.N   = N
        self.dim = dim
        self.k   = k
        self.EPS = 1e-8

        # ---- CRF constants (delta-chain) ----
        self.alpha   = np.log(2)
        self.I_eff   = 0.7007
        self.eps0    = abs(self.I_eff - self.alpha)   # ~0.00755
        self.D0      = 0.9403
        self.kappa   = 0.15
        self.SINDY_T = 0.02
        self.sigma   = 0.5    # Psi selective coupling scale

        # ---- IDV-metric coupling ----
        # lambda tunes IDV influence on 3D metric
        # too large: d_s crashes below 3 / too small: no effect
        self.lam_idv = 0.002

        # ---- States ----
        self.P          = self._init_P()
        self.X          = self._init_X()
        self._add_spatial_bias()
        self.metric     = [np.eye(dim) for _ in range(N)]
        self.local_time = np.zeros(N)
        self.node_mass  = np.ones(N)

        # ---- Wave layer (Phi, Psi) ----
        self.Phi = np.random.rand(N) * 2 * np.pi
        self.Psi = np.random.randn(N) * 0.1

        # ---- Logs ----
        self.gravity_logs  = []
        self.ds_history    = []
        self.theta_history = []
        self.r_history     = []
        self.idv_history   = []    # mean IDV per sweep
        self.dint_history  = []    # mean d_int per sweep
        self.psi_snapshots = []    # Psi distribution at intervals

    # =====================================================
    # Init
    # =====================================================
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

    # =====================================================
    # Vectorized KL
    # =====================================================
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

    # =====================================================
    # Phi wave field update
    # Phi_i += eta * sum_j(KL_ij * sin(Phi_j - Phi_i))
    # =====================================================
    def _update_phi(self, KL, idx):
        eta     = 0.05
        new_Phi = self.Phi.copy()
        for i in range(self.N):
            nb   = idx[i]
            dPhi = np.sin(self.Phi[nb] - self.Phi[i])
            kl_i = KL[i, nb]
            new_Phi[i] += eta * np.mean(kl_i * dPhi)
        self.Phi = new_Phi % (2 * np.pi)

    # =====================================================
    # Psi mode update (pattern identity)
    # Psi_i <- 0.9*Psi_i + 0.1*mean_selective + eps0*noise
    # selective coupling: exp(-|Psi_i - Psi_j| / sigma)
    # =====================================================
    def _update_psi(self, idx):
        new_Psi = self.Psi.copy()
        for i in range(self.N):
            nb  = idx[i]
            sel = np.exp(-np.abs(self.Psi[nb] - self.Psi[i]) / self.sigma)
            sel_sum = sel.sum() + self.EPS
            nb_mean = np.sum(self.Psi[nb] * sel) / sel_sum
            new_Psi[i] = (0.9 * self.Psi[i]
                          + 0.1 * nb_mean
                          + self.eps0 * np.random.randn())
        self.Psi = new_Psi

    # =====================================================
    # IDV: Internal Dimensional Volume
    # V_i = H(P_i) * (1 + phi_var) * (1 + |grad_Psi|) * ln(1+mass)
    # d_int_i = ln(1 + V_i)
    # =====================================================
    def _compute_idv(self, idx):
        # Entropy H(P_i)
        H_P = -(self.P * np.log(self.P + self.EPS)).sum(axis=1)

        phi_var  = np.zeros(self.N)
        psi_grad = np.zeros(self.N)
        for i in range(self.N):
            nb           = idx[i]
            cos_diffs    = np.cos(self.Phi[nb] - self.Phi[i])
            phi_var[i]   = np.var(cos_diffs)
            psi_grad[i]  = np.mean(np.abs(self.Psi[nb] - self.Psi[i]))

        V_int = (H_P
                 * (1.0 + phi_var)
                 * (1.0 + psi_grad)
                 * np.log1p(self.node_mass))
        d_int = np.log1p(V_int)
        return V_int, d_int

    # =====================================================
    # Tension / threshold (same as V16)
    # =====================================================
    def _compute_tension_threshold(self, KL, idx):
        tension   = np.zeros(self.N)
        threshold = np.zeros(self.N)
        for i in range(self.N):
            nb         = idx[i]
            kl_mean    = np.mean(KL[i, nb])
            tension[i] = np.mean(KL[i, nb] * np.sqrt(self.node_mass[nb]))
            theta_i    = 1.0 - np.exp(-kl_mean / self.D0)
            threshold[i] = theta_i * np.sqrt(self.node_mass[i])
        return tension, threshold

    # =====================================================
    # Born rule resolution
    # =====================================================
    def _born_resolve(self, i, idx_i):
        target  = np.mean(self.P[idx_i], axis=0)
        alpha_d = (target + self.eps0) / self.eps0
        return np.maximum(np.random.dirichlet(alpha_d), self.EPS)

    # =====================================================
    # Metric leap + IDV coupling (3D slice)
    # Standard: G += 0.01 * outer(curv, curv)
    # IDV:      G[:3,:3] += lam * IDV_i * cos(Phi) * r3 outer r3
    # =====================================================
    def _metric_leap(self, i, idx_i, KL, IDV_i):
        curv = np.zeros(self.dim)
        for j in idx_i:
            curv += KL[i, j] * (self.X[j] - self.X[i])
        curv /= self.k

        align = np.mean(self.X[idx_i], axis=0) - self.X[i]
        move  = 0.1 * curv + 0.05 * align + self.eps0 * np.random.randn(self.dim)
        self.X[i] += move

        # Standard metric update
        G  = self.metric[i] + 0.01 * np.outer(curv, curv)

        # IDV-driven 3D coupling (SO3 forces 3D subspace)
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
                    ev[j]   = self.eps0 + np.random.rand() * self.eps0 * 0.1
                    changed = True
            if changed:
                self.metric[i] = evec @ np.diag(ev) @ evec.T
            for d in range(3, self.dim):
                if abs(self.X[i, d]) < self.SINDY_T:
                    self.X[i, d] = np.sign(self.X[i, d]) * self.eps0

    # =====================================================
    # Gravity probe — Omega field (same as V16, canonical)
    # =====================================================
    def _measure_gravity(self, core_nodes, t_e):
        if len(core_nodes) < 2:
            return
        pairs = []
        non_cores  = [n for n in range(self.N) if n not in set(core_nodes)]
        extra      = (np.random.choice(non_cores,
                                       size=min(50, len(non_cores)),
                                       replace=False).tolist()
                      if non_cores else [])
        all_sample = list(core_nodes) + extra
        for i in core_nodes:
            Omega_i = self.node_mass[i] - 1.0
            if Omega_i <= 0:
                continue
            for j in all_sample:
                if i == j:
                    continue
                Omega_j = self.node_mass[j] - 1.0
                if Omega_j <= 0:
                    continue
                r_sq  = float(np.dot(self.X[i,:3]-self.X[j,:3],
                                     self.X[i,:3]-self.X[j,:3])) + self.EPS
                crf_c = (Omega_i * Omega_j) / r_sq
                theo  = (self.node_mass[i] * self.node_mass[j]) / r_sq
                if crf_c > 1e-8 and theo > 1e-8:
                    pairs.append((theo, crf_c))
        if pairs:
            self.gravity_logs.append({"time": t_e, "pairs": pairs})

    # =====================================================
    # d_s from random-walk return (canonical)
    # =====================================================
    def _estimate_ds(self, idx):
        returns    = []
        walk_times = list(range(2, 20, 2))
        for wt in walk_times:
            hits = 0
            for start in range(0, self.N, 10):
                curr = start
                for _ in range(wt):
                    curr = int(idx[curr, np.random.randint(self.k)])
                if curr == start:
                    hits += 1
            p_ret = hits / (self.N / 10 + self.EPS)
            returns.append(max(p_ret, 1e-4))
        log_t = np.log(walk_times)
        log_p = np.log(returns)
        if np.std(log_p) < 0.25:
            return np.nan
        slope, _ = np.polyfit(log_t, log_p, 1)
        return -2.0 * slope

    def _detect_cores(self, n=50):
        top = np.argsort(self.local_time)[-n:]
        return [i for i in top if self.local_time[i] > 1]

    # =====================================================
    # Main sweep
    # =====================================================
    def sweep(self, sweep_idx):
        KL  = self._kl_matrix()
        idx = self._get_neighbors(KL)

        # Wave layer updates
        self._update_phi(KL, idx)
        self._update_psi(idx)

        # Background distinction (eps0)
        self.P += self.eps0 * np.random.randn(self.N, self.dim)
        self.P  = np.maximum(self.P, self.EPS)
        self.P /= self.P.sum(axis=1, keepdims=True)

        # Mass
        self.node_mass = 1.0 + self.local_time * self.kappa

        # IDV
        V_int, d_int = self._compute_idv(idx)
        self.idv_history.append(float(np.mean(V_int)))
        self.dint_history.append(float(np.mean(d_int)))

        # Tension / threshold
        tension, threshold = self._compute_tension_threshold(KL, idx)

        # R-events
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
        print(f"CRF Hybrid V17  N={self.N}  eps0={self.eps0:.5f}  "
              f"lam_idv={self.lam_idv}")
        print(f"Phi wave + Psi modes + IDV-metric(3D) | gravity: Omega·Omega/r²")
        print("-" * 72)
        for s in range(max_sweeps):
            t_e, r_ev, ds, th, mass, trig, idv_m = self.sweep(s)
            if s % 25 == 0:
                ds_str = f"{ds:6.3f}" if not np.isnan(ds) else "   NaN"
                tag    = "  G" if trig else ""
                print(f"sweep {s:3d} | t={t_e:5.2f} | R={r_ev:4d} | "
                      f"d_s={ds_str} | IDV={idv_m:.3f} | mass={mass:.2f}x{tag}")


# =====================================================
# Analytics
# =====================================================
def analyze(sim, save_path="/mnt/user-data/outputs/CRF_V17_results.png"):
    fig, axs = plt.subplots(2, 3, figsize=(18, 10))
    fig.suptitle("CRF Hybrid V17 — CWRC + IDV + Marble Effect", fontsize=13)

    # 1. Gravity
    logs = sim.gravity_logs
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
        axs[0,0].set_xlabel(r"$m_1m_2/r^2$"); axs[0,0].set_ylabel(r"$\Omega_i\Omega_j/r^2$")
        axs[0,0].set_title(f"Gravity  $G_{{sim}}$={G_sim:.4f}  ln2={np.log(2):.4f}")
        axs[0,0].legend()

    # 2. d_s convergence
    ds_arr = np.array(sim.ds_history)
    axs[0,1].plot(ds_arr, color="steelblue", alpha=0.7, lw=1)
    axs[0,1].axhline(3.0, color="red", ls="--", lw=1.5, label="target 3")
    valid = ds_arr[~np.isnan(ds_arr)]
    if len(valid) > 20:
        late = np.mean(valid[-50:])
        axs[0,1].axhline(late, color="orange", ls=":", label=f"late={late:.2f}")
    axs[0,1].set_ylim(0, 8); axs[0,1].set_xlabel("Sweep")
    axs[0,1].set_ylabel("d_s"); axs[0,1].set_title("Spectral Dimension")
    axs[0,1].legend()

    # 3. IDV (Internal Dimensional Volume)
    idv_arr  = np.array(sim.idv_history)
    dint_arr = np.array(sim.dint_history)
    axs[0,2].plot(idv_arr,  color="teal",    lw=1.5, label=r"$\overline{V^{int}}$")
    axs[0,2].set_ylabel(r"$\overline{V^{int}}$", color="teal")
    ax2 = axs[0,2].twinx()
    ax2.plot(dint_arr, color="purple", lw=1.5, alpha=0.7, label=r"$\overline{d^{int}}$")
    ax2.set_ylabel(r"$\overline{d^{int}}$", color="purple")
    axs[0,2].set_xlabel("Sweep")
    axs[0,2].set_title("Internal Dimensional Inflation (IDI)")

    # 4. Phi variance (wave activity)
    # Approximate from R-events per sweep
    r_arr = np.array(sim.r_history)
    axs[1,0].bar(range(len(r_arr)), r_arr / sim.N * 100, alpha=0.6,
                 color="steelblue", width=1)
    axs[1,0].set_xlabel("Sweep"); axs[1,0].set_ylabel("R-events (%)")
    axs[1,0].set_title(r"R-events per sweep")

    # 5. Psi speciation histogram (final snapshot)
    if sim.psi_snapshots:
        axs[1,1].hist(sim.psi_snapshots[-1], bins=40,
                      color="darkorange", edgecolor="black", alpha=0.8)
        axs[1,1].set_xlabel(r"$\Psi$ (pattern mode)")
        axs[1,1].set_ylabel("Node count")
        axs[1,1].set_title(r"Speciation: $\Psi$ distribution (final)")

    # 6. IDV vs d_s scatter
    if len(idv_arr) > 0 and len(valid) > 0:
        min_len = min(len(idv_arr), len(ds_arr))
        ds_trim  = ds_arr[:min_len]
        idv_trim = idv_arr[:min_len]
        mask = ~np.isnan(ds_trim)
        axs[1,2].scatter(idv_trim[mask], ds_trim[mask],
                         alpha=0.4, s=10, color="purple")
        axs[1,2].axhline(3.0, color="red", ls="--", lw=1)
        axs[1,2].set_xlabel(r"$\overline{V^{int}}$")
        axs[1,2].set_ylabel("d_s")
        axs[1,2].set_title("IDV vs d_s (Marble Effect probe)")

    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches="tight")
    print(f"Plot: {save_path}")

    # Summary
    ds_late = np.mean(valid[-50:]) if len(valid) > 20 else float('nan')
    G_sim_v = 10**intercept if logs else float('nan')
    R2_v    = r_val**2 if logs else float('nan')

    print(f"\n{'='*60}")
    print(f"CRF V17 — Results")
    print(f"{'='*60}")
    print(f"Gravity R²       = {R2_v:.4f}   (V16: 0.906)")
    print(f"Slope            = {slope:.4f}   (target +1.0)")
    print(f"G_sim            = {G_sim_v:.5f}")
    print(f"G_sim/ln2        = {G_sim_v/np.log(2):.4f}")
    print(f"d_s late mean    = {ds_late:.4f}   (target 3.0)")
    print(f"IDV final mean   = {idv_arr[-1]:.4f}")
    print(f"d_int final mean = {dint_arr[-1]:.4f}")
    print(f"eps0             = {sim.eps0:.5f}")
    print(f"lam_idv          = {sim.lam_idv}")
    print(f"{'='*60}")


if __name__ == "__main__":
    sim = CRFHybridV17(N=500, dim=8, k=20)
    sim.run(max_sweeps=400)
    print("\nAnalyzing...")
    analyze(sim)
