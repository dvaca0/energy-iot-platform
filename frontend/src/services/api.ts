// @ts-nocheck
import axios from "axios";

export const api = axios.create({
  baseURL: "http://127.0.0.1:8010/api",
  timeout: 30000,
});

export async function getDashboardSummary() {
  const response = await api.get("/dashboard/summary");
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

export async function getMetricsHourly() {
  const response = await api.get("/metrics/hourly");
  return response.data;
}

export async function getMetricsTariffs() {
  const response = await api.get("/metrics/tariffs");
  return response.data;
}

export async function getMetricsDaily() {
  const response = await api.get("/metrics/daily");
  return response.data;
}

export async function getMetricsBuildings() {
  const response = await api.get("/metrics/buildings");
  return response.data;
}

export async function getAnomalies() {
  const response = await api.get("/anomalies");
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
  const response = await fetch("http://127.0.0.1:8010/api/ai-center/assistant", {
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
