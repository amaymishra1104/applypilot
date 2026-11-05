import axios from "axios";

export const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

export const api = axios.create({ baseURL: API, withCredentials: true });

api.interceptors.response.use(undefined, (error) => {
  const detail = error?.response?.data?.detail;
  if (Array.isArray(detail)) {
    error.response.data.detail = detail.map((d) => d?.msg || String(d)).join("; ");
  }
  if (error?.response?.status === 401) {
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login") && !window.location.pathname.startsWith("/sign-in")) {
      window.location.href = "/login";
    }
  }
  return Promise.reject(error);
});

export const authQueryParam = async () => "";

export const fetchBlobUrl = async (path) => {
  const res = await api.get(path, { responseType: "blob" });
  return URL.createObjectURL(res.data);
};

export const downloadFile = async (path, filename) => {
  const res = await api.get(path, { responseType: "blob" });
  const url = URL.createObjectURL(res.data);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
};

export const downloadCsv = async (path) => {
  const res = await api.get(path, { responseType: "blob" });
  const url = URL.createObjectURL(res.data);
  const a = document.createElement("a");
  a.href = url;
  a.download = "applypilot-applications.csv";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
};
