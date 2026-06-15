import axios from "axios";

export const api = axios.create({
  baseURL: "http://127.0.0.1:8010/api",
  timeout: 8000,
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
