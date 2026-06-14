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
