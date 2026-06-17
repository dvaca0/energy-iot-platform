from pathlib import Path
import re

app = Path("src/App.tsx")
txt = app.read_text()

helper = r'''
const getCurrentPlatformSubtitle = () => {
  const now = new Date();
  const day = now.getDay() || 7;
  const monday = new Date(now);
  monday.setDate(now.getDate() - day + 1);
  const sunday = new Date(monday);
  sunday.setDate(monday.getDate() + 6);
  const months = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"];
  return `Universidad de Colima · GDMTH · Semana del ${monday.getDate()}–${sunday.getDate()} ${months[sunday.getMonth()]} ${sunday.getFullYear()}`;
};

const formatConfidence = (value) => {
  if (value === null || value === undefined) return "Datos insuficientes";
  const n = Number(value);
  if (Number.isNaN(n)) return "Datos insuficientes";
  return `${Math.round(n * 100)}%`;
};
'''

if "getCurrentPlatformSubtitle" not in txt:
    txt = txt.replace("// ─── HELPERS", helper + "\n// ─── HELPERS")

txt = txt.replace("Universidad de Colima · GDMTH · Semana del 6–13 Ene 2025", "{getCurrentPlatformSubtitle()}")

txt = txt.replace("+8% vs sem. anterior", "Histórico insuficiente")
txt = txt.replace("+12% vs sem. anterior", "Histórico insuficiente")

txt = re.sub(
    r'(\{[^{}]*?aiCenter[^{}]*?forecast[^{}]*?confidence[^{}]*?\}\s*%?)',
    r'{formatConfidence(aiCenter?.forecast?.confidence)}',
    txt
)

txt = txt.replace("Confianza", "Confianza por backtesting")

# Add a small dashboard range selector only if a dashboard header-like area exists.
if "dashboard-range-selector" not in txt:
    txt = txt.replace(
        "const [",
        "const [dashboardRange, setDashboardRange] = useState('week');\n  const [",
        1
    )

css = Path("src/App.css")
css_txt = css.read_text()
if ".dashboard-range-selector" not in css_txt:
    css_txt += r'''

.dashboard-range-selector {
  display: inline-flex;
  gap: 6px;
  background: rgba(16, 16, 30, 0.9);
  border: 1px solid #1f1b37;
  border-radius: 999px;
  padding: 4px;
}

.dashboard-range-selector button {
  border: 0;
  background: transparent;
  color: #8d86af;
  padding: 7px 12px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}

.dashboard-range-selector button.active {
  background: rgba(124, 92, 191, 0.28);
  color: #d8ccff;
}
'''
    css.write_text(css_txt)

app.write_text(txt)
print("Frontend safe patch complete.")
