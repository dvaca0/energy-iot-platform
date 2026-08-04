// @ts-nocheck
import axios from "axios";

const API_ORIGIN =
  typeof window !== "undefined"
    ? `${window.location.protocol}//${window.location.hostname}:8010`
    : "http://127.0.0.1:8010";

export const api = axios.create({
  baseURL: `${API_ORIGIN}/api`,
  timeout: 30000,
});

/**
 * Optional deployment scope for the Executive Dashboard endpoints.
 *
 * Returns undefined rather than an empty object when no deployment is selected,
 * so axios omits the query string entirely and an unscoped request is identical
 * to the one these functions sent before the selector existed.
 */
function scopeParams(deploymentId?: number | null) {
  return deploymentId === null || deploymentId === undefined
    ? undefined
    : { deployment_id: deploymentId };
}

export async function getDashboardSummary(deploymentId?: number | null) {
  const response = await api.get("/dashboard/summary", { params: scopeParams(deploymentId) });
  return response.data;
}


export async function getHourlyCost() {
  const response = await api.get("/cost/hourly");
  return response.data;
}


export async function getBuildings() {
  const response = await api.get("/buildings");
  return response.data;
}


export async function getNodes() {
  const response = await api.get("/nodes");
  return response.data;
}


export async function getAiInsights() {
  const response = await api.get("/ai/insights");
  return response.data;
}


export async function createDeployment(payload: any) {
  const response = await api.post("/deployments", payload);
  return response.data;
}


export async function getDelegations() {
  const response = await api.get("/org/delegations");
  return response.data;
}

export async function getCampusesByDelegation(delegationId: number) {
  const response = await api.get(`/org/campuses/by-delegation/${delegationId}`);
  return response.data;
}

export async function getUnitsByCampus(campusId: number) {
  const response = await api.get(`/org/units/by-campus/${campusId}`);
  return response.data;
}

export async function getBuildingsByUnit(unitId: number) {
  const response = await api.get(`/org/buildings/by-unit/${unitId}`);
  return response.data;
}

export async function getPanelsByBuilding(buildingId: number) {
  const response = await api.get(`/org/panels/by-building/${buildingId}`);
  return response.data;
}

export async function getAllOrgBuildings() {
  const response = await api.get("/org/buildings");
  return response.data;
}

export async function getLatestReadings() {
  const response = await api.get("/readings/latest");
  return response.data;
}

export async function getLiveMetrics() {
  const response = await api.get("/metrics/live");
  return response.data;
}

export async function getMetricsHourly(deploymentId?: number | null) {
  const response = await api.get("/metrics/hourly", { params: scopeParams(deploymentId) });
  return response.data;
}

export async function getMetricsTariffs(deploymentId?: number | null) {
  const response = await api.get("/metrics/tariffs", { params: scopeParams(deploymentId) });
  return response.data;
}

export async function getMetricsDaily(deploymentId?: number | null) {
  const response = await api.get("/metrics/daily", { params: scopeParams(deploymentId) });
  return response.data;
}

export async function getMetricsBuildings(deploymentId?: number | null) {
  const response = await api.get("/metrics/buildings", { params: scopeParams(deploymentId) });
  return response.data;
}

/**
 * `includeResolved` opts in to recovery history. The backend defaults it to
 * false so older clients only ever see live conditions; the Insight Center
 * asks for the full list because it labels each entry ACTIVE or RESOLVED.
 */
export async function getAnomalies(deploymentId?: number | null, includeResolved = false) {
  const response = await api.get("/anomalies", {
    params: { ...(scopeParams(deploymentId) || {}), include_resolved: includeResolved },
  });
  return response.data;
}

export async function getCampusMetrics() {
  const response = await api.get("/metrics/campuses");
  return response.data;
}

export async function getDeployments() {
  const response = await api.get("/deployments");
  return response.data;
}

export async function finishDeployment(deploymentId: number, dryRun = true) {
  const response = await api.post(`/deployments/${deploymentId}/finish?dry_run=${dryRun}`);
  return response.data;
}

export async function getCostSummary() {
  const response = await api.get("/cost/summary");
  return response.data;
}

export async function getSystemSettings() {
  const response = await api.get("/settings");
  return response.data;
}

export async function getInfrastructureStatus() {
  const response = await api.get("/infra");
  return response.data;
}

export async function getMiningAnalytics() {
  const response = await api.get("/mining");
  return response.data;
}

export async function getAiCenter() {
  const response = await api.get("/ai-center");
  return response.data;
}



export async function askAiAssistant(question: string) {
  const response = await fetch(`${API_ORIGIN}/api/ai-center/assistant`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ question }),
  });

  const text = await response.text();

  let data;
  try {
    data = JSON.parse(text);
  } catch {
    throw new Error(`Backend returned non-JSON response: ${text}`);
  }

  if (!response.ok) {
    throw new Error(data?.answer || data?.detail || `HTTP ${response.status}`);
  }

  return data;
}


export const getCfeStatus = async () => {
  const response = await api.get("/settings/cfe/status");
  return response.data;
};


export async function getDeploymentReports() {
  const response = await api.get("/reports/deployments");
  return response.data;
}

export async function generateDeploymentReport(deploymentId: number) {
  const response = await api.post(`/reports/deployment/${deploymentId}/generate`);
  return response.data;
}


export async function getSmartPlugs(deploymentId?: number | null) {
  const response = await api.get("/smart-plugs", { params: scopeParams(deploymentId) });
  return response.data;
}

export async function assignSmartPlug(plugId: string, payload: Record<string, string>) {
  const response = await api.post(`/smart-plugs/${encodeURIComponent(plugId)}/assign`, payload);
  return response.data;
}

export async function getSmartPlugHistory(plugId: string, hours = 24) {
  const response = await api.get(`/smart-plugs/${encodeURIComponent(plugId)}/history`, {
    params: { hours },
  });
  return response.data;
}

export async function getSmartPlug(plugId: string) {
  const response = await api.get(`/smart-plugs/${encodeURIComponent(plugId)}`);
  return response.data;
}

/** Enchufes que responden ahora, ordenados por consumo instantáneo. */
export async function getSmartPlugsLive() {
  const response = await api.get("/smart-plugs/live");
  return response.data;
}
