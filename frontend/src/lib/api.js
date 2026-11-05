import axios from "axios";

export const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

let getTokenFn = null;
export const setTokenGetter = (fn) => {
  getTokenFn = fn;
};

export const api = axios.create({ baseURL: API });

api.interceptors.request.use(async (config) => {
  if (getTokenFn) {
    try {
      const token = await getTokenFn();
      if (token) config.headers.Authorization = `Bearer ${token}`;
    } catch (e) {
      // token unavailable; request goes out unauthenticated and fails with 401
    }
  }
  return config;
});

api.interceptors.response.use(undefined, (error) => {
  const detail = error?.response?.data?.detail;
  if (Array.isArray(detail)) {
    error.response.data.detail = detail.map((d) => d?.msg || String(d)).join("; ");
  }
  return Promise.reject(error);
});

export const authQueryParam = async () => {
  if (!getTokenFn) return "";
  const token = await getTokenFn();
  return `?auth=${encodeURIComponent(token)}`;
};

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
