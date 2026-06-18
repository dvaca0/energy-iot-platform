import React, { useEffect, useState } from "react";
import { Zap, DollarSign, Sparkles, Server, User, Lock, Eye, EyeOff, LogIn } from "lucide-react";
import { api } from "../services/api";

const USERS = {
  "admin@ucol.mx": { pass: "admin123", role: "Administrador" },
  "ejecutivo@ucol.mx": { pass: "exec2025", role: "Ejecutivo" },
  "tecnico@ucol.mx": { pass: "tech2025", role: "Técnico" },
  "investigador@ucol.mx": { pass: "inv2025", role: "Investigador" },
};

export default function LoginPage({ onLogin }) {
  const [role, setRole] = useState("Administrador");
  const [email, setEmail] = useState("admin@ucol.mx");
  const [password, setPassword] = useState("admin123");
  const [showPw, setShowPw] = useState(false);
  const [alert, setAlert] = useState(null);
  const [loading, setLoading] = useState(false);
  const [systemStatus, setSystemStatus] = useState({
    activeNodes: 0,
    totalNodes: 0,
    syncActive: false,
    warnings: 0,
    operational: false,
  });

  useEffect(() => {
    const loadStatus = async () => {
      try {
        const [nodesRes, anomaliesRes] = await Promise.allSettled([
          api.get("/nodes"),
          api.get("/anomalies"),
        ]);

        const nodes = nodesRes.status === "fulfilled" ? nodesRes.value.data || [] : [];
        const anomalies = anomaliesRes.status === "fulfilled" ? anomaliesRes.value.data || {} : {};

        const activeNodes = nodes.filter((node) => node.status === "online").length;
        const totalNodes = nodes.length;
        const warnings =
          Number(anomalies.today_count || 0) ||
          Number(anomalies.week_count || 0) ||
          (Array.isArray(anomalies.items) ? anomalies.items.length : 0);

        setSystemStatus({
          activeNodes,
          totalNodes,
          syncActive: activeNodes > 0,
          warnings,
          operational: activeNodes > 0,
        });
      } catch (error) {
        console.error("Login status load error:", error);
      }
    };

    loadStatus();
  }, []);

  const fillDemo = (user, pass) => {
    setEmail(user);
    setPassword(pass);
    setRole(USERS[user]?.role || "Administrador");
    setAlert(null);
  };

  const submit = (e) => {
    e.preventDefault();
    setAlert(null);
    const clean = email.trim().toLowerCase();

    if (!clean || !password) {
      setAlert({ type: "error", text: "Ingresa usuario y contraseña." });
      return;
    }

    setLoading(true);
    setTimeout(() => {
      const user = USERS[clean];
      if (!user || user.pass !== password) {
        setAlert({ type: "error", text: "Correo o contraseña incorrectos." });
        setLoading(false);
        return;
      }

      localStorage.setItem("energy_auth", "true");
      localStorage.setItem("energy_role", user.role);\n      localStorage.setItem("energy_user", clean);
      onLogin(user.role);
    }, 500);
  };

  return (
    <div style={{
      minHeight: "100vh",
      background: "#080811",
      color: "#e8e6f4",
      display: "flex",
      fontFamily: "Inter, system-ui, sans-serif",
      backgroundImage: "linear-gradient(rgba(109,82,184,.04) 1px,transparent 1px),linear-gradient(90deg,rgba(109,82,184,.04) 1px,transparent 1px)",
      backgroundSize: "40px 40px"
    }}>
      <section style={{
        flex: 1,
        padding: "48px 56px",
        borderRight: "1px solid #14142a",
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between"
      }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 11, marginBottom: 56 }}>
            <div style={{
              width: 36, height: 36, borderRadius: 9,
              background: "linear-gradient(135deg,#6d52b8,#3d2d8a)",
              display: "flex", alignItems: "center", justifyContent: "center"
            }}>
              <Zap size={17} color="#fff" />
            </div>
            <div>
              <div style={{ fontSize: 13, fontWeight: 800 }}>Energy IQ</div>
              <div style={{ fontSize: 9.5, color: "#4a4768", letterSpacing: .9, textTransform: "uppercase" }}>UCol Platform</div>
            </div>
          </div>

          <div style={{ maxWidth: 460 }}>
            <h1 style={{ fontSize: 32, lineHeight: 1.15, margin: "0 0 16px", letterSpacing: -1 }}>
              Intelligent Energy<br />Operations Center
            </h1>
            <p style={{ color: "#8a87a8", lineHeight: 1.7, marginBottom: 40 }}>
              Monitoreo, análisis de costo y detección de anomalías energéticas para la Universidad de Colima.
            </p>

            {[
              [DollarSign, "Análisis de Costo en Tiempo Real", "Estimación bajo tarifa GDMTH con desglose por periodo base, intermedia y punta."],
              [Sparkles, "Centro IA & Forecasting", "Detección de anomalías, proyección de consumo y recomendaciones de ahorro automatizadas."],
              [Server, "Edge Nodes & Despliegues", "Gestión de nodos Shelly + Raspberry Pi con sincronía en campo vía Tailscale VPN."]
            ].map(([Icon, title, text]) => (
              <div key={title} style={{ display: "flex", gap: 12, marginBottom: 20 }}>
                <div style={{
                  width: 34, height: 34, borderRadius: 8,
                  background: "rgba(109,82,184,.08)",
                  border: "1px solid rgba(109,82,184,.15)",
                  display: "flex", alignItems: "center", justifyContent: "center"
                }}>
                  <Icon size={15} color="#9b7de0" />
                </div>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 700 }}>{title}</div>
                  <div style={{ fontSize: 12, color: "#4a4768", lineHeight: 1.55 }}>{text}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div style={{ borderTop: "1px solid #14142a", paddingTop: 18, display: "flex", gap: 18, color: "#8a87a8", fontSize: 11.5, alignItems: "center" }}>
          <span style={{ color: systemStatus.activeNodes > 0 ? "#22c55e" : "#ef4444" }}>
            ● {systemStatus.activeNodes}/{systemStatus.totalNodes} nodo{systemStatus.totalNodes === 1 ? "" : "s"} operativo{systemStatus.activeNodes === 1 ? "" : "s"}
          </span>
          <span style={{ color: systemStatus.syncActive ? "#22c55e" : "#f59e0b" }}>
            ● {systemStatus.syncActive ? "Sincronía activa" : "Sin sincronía activa"}
          </span>
          <span style={{ color: systemStatus.warnings > 0 ? "#f59e0b" : "#22c55e" }}>
            ● {systemStatus.warnings} advertencia{systemStatus.warnings === 1 ? "" : "s"}
          </span>
          <span style={{
            marginLeft: "auto",
            color: systemStatus.operational ? "#22c55e" : "#ef4444",
            border: `1px solid ${systemStatus.operational ? "rgba(34,197,94,.18)" : "rgba(239,68,68,.18)"}`,
            background: systemStatus.operational ? "rgba(34,197,94,.08)" : "rgba(239,68,68,.08)",
            borderRadius: 4,
            padding: "3px 9px",
            fontSize: 10.5,
            fontWeight: 800
          }}>
            {systemStatus.operational ? "Sistema operativo" : "Sistema sin nodos activos"}
          </span>
        </div>
      </section>

      <section style={{ width: 480, padding: "56px 52px", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <div style={{ width: "100%", maxWidth: 360 }}>
          <h2 style={{ fontSize: 22, margin: "0 0 6px" }}>Iniciar sesión</h2>
          <div style={{ color: "#4a4768", fontSize: 13, marginBottom: 28 }}>Accede con tus credenciales institucionales</div>

          <div style={{ marginBottom: 22 }}>
            <div style={{ fontSize: 11, color: "#4a4768", textTransform: "uppercase", letterSpacing: .9, marginBottom: 8 }}>Perfil de acceso</div>
            <div style={{ display: "flex", gap: 6 }}>
              {["Administrador", "Ejecutivo", "Técnico", "Investigador"].map((r) => (
                <button key={r} onClick={() => setRole(r)} style={{
                  flex: 1, padding: "9px 0", borderRadius: 7,
                  border: role === r ? "1px solid rgba(109,82,184,.55)" : "1px solid #1c1c32",
                  background: role === r ? "rgba(109,82,184,.12)" : "#111120",
                  color: role === r ? "#9b7de0" : "#8a87a8",
                  fontSize: 12, cursor: "pointer"
                }}>{r}</button>
              ))}
            </div>
          </div>

          {alert && (
            <div style={{
              marginBottom: 16, padding: "11px 14px", borderRadius: 8,
              background: alert.type === "error" ? "rgba(239,68,68,.07)" : "rgba(34,197,94,.07)",
              border: alert.type === "error" ? "1px solid rgba(239,68,68,.2)" : "1px solid rgba(34,197,94,.2)",
              color: alert.type === "error" ? "#f87171" : "#22c55e",
              fontSize: 12.5
            }}>{alert.text}</div>
          )}

          <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <label style={{ fontSize: 11.5, color: "#4a4768", textTransform: "uppercase", letterSpacing: .9 }}>Usuario / Correo institucional</label>
            <div style={{ position: "relative" }}>
              <User size={14} color="#4a4768" style={{ position: "absolute", left: 13, top: 13 }} />
              <input value={email} onChange={(e) => setEmail(e.target.value)} style={inputStyle} />
            </div>

            <label style={{ fontSize: 11.5, color: "#4a4768", textTransform: "uppercase", letterSpacing: .9 }}>Contraseña</label>
            <div style={{ position: "relative" }}>
              <Lock size={14} color="#4a4768" style={{ position: "absolute", left: 13, top: 13 }} />
              <input type={showPw ? "text" : "password"} value={password} onChange={(e) => setPassword(e.target.value)} style={inputStyle} />
              <button type="button" onClick={() => setShowPw(!showPw)} style={{ position: "absolute", right: 10, top: 9, background: "none", border: 0, color: "#4a4768", cursor: "pointer" }}>
                {showPw ? <EyeOff size={15} /> : <Eye size={15} />}
              </button>
            </div>

            <button disabled={loading} style={{
              marginTop: 6, padding: 12, border: 0, borderRadius: 8,
              background: "linear-gradient(135deg,#6d52b8,#4a35a0)",
              color: "#fff", fontWeight: 800, cursor: "pointer",
              display: "flex", alignItems: "center", justifyContent: "center", gap: 8
            }}>
              <LogIn size={14} /> {loading ? "Verificando..." : "Iniciar sesión"}
            </button>
          </form>

          <div style={{ margin: "24px 0", height: 1, background: "#14142a" }} />

          <div style={{ background: "#0d0d1a", border: "1px solid rgba(109,82,184,.35)", borderRadius: 10, padding: 16 }}>
            <div style={{ fontSize: 10.5, color: "#4a4768", textTransform: "uppercase", letterSpacing: .9, fontWeight: 800, marginBottom: 10 }}>
              Credenciales de prueba
            </div>
            {[
              ["admin@ucol.mx", "admin123", "Administrador · acceso completo"],
              ["ejecutivo@ucol.mx", "exec2025", "Ejecutivo · costos y reportes"],
              ["tecnico@ucol.mx", "tech2025", "Técnico · nodos y despliegues"],
              ["investigador@ucol.mx", "inv2025", "Investigador · datos y análisis"]
            ].map(([u, p, d]) => (
              <div key={u} onClick={() => fillDemo(u, p)} style={{ padding: "9px 10px", background: "#111120", border: "1px solid #14142a", borderRadius: 7, marginBottom: 7, cursor: "pointer", display: "flex", justifyContent: "space-between" }}>
                <div>
                  <div style={{ fontSize: 12, fontWeight: 700 }}>{u}</div>
                  <div style={{ fontSize: 11, color: "#4a4768" }}>{d}</div>
                </div>
                <span style={{ fontSize: 11, color: "#8a87a8" }}>{p}</span>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}

const inputStyle = {
  width: "100%",
  background: "#111120",
  border: "1px solid #1c1c32",
  color: "#e8e6f4",
  borderRadius: 8,
  padding: "11px 40px",
  fontSize: 13.5,
  outline: "none"
};
