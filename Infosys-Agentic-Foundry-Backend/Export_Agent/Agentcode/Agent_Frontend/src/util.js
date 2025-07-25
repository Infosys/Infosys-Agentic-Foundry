import { updateTools } from "./services/toolService";

export const storeLocalStorageData = (key, value) => {
  localStorage.setItem(key, JSON.stringify(value));
};

export const getLocalStorageData = (key) => {
  const data = localStorage.getItem(key);
  return data ? JSON.parse(data) : null;
};

export const updateLocalStorageData = (key, newValue) => {
  if (localStorage.getItem(key)) {
    localStorage.setItem(key, JSON.stringify(newValue));
  } else {
    console.error(`No data found for key`);
  }
};

export const deleteLocalStorage = (key) => {
  localStorage.removeItem(key);
};

export const isEmptyObj = (obj) =>
  obj === null || (typeof obj === "object" && Object.keys(obj).length === 0);

export const calculateDivs = (containerRef, cardWidth, cardHeight, flexGap) => {
  if (containerRef.current) {
    const containerWidth = containerRef.current.offsetWidth;
    const containerHeight = containerRef.current.offsetHeight;

    const maxDivsInRow = Math.ceil(
      (containerWidth + flexGap) / (cardWidth + flexGap)
    );

    const maxDivsInColumn = Math.ceil(
      (containerHeight + flexGap) / (cardHeight + flexGap)
    );

    const totalDivs = maxDivsInRow * maxDivsInColumn;
    return totalDivs;
  }
};

export const checkToolEditable = async (
  tool,
  setShowForm,
  addMessage,
  setLoading,
) => {
  let response;
  const updatedTool = { ...tool, user_email_id: tool.created_by };
  if(setLoading)  setLoading(true);
  response = await updateTools(updatedTool, tool.tool_id);
  if(setLoading) setLoading(false);
  if (response?.is_update) {
    setShowForm(true);
    return true;
  } else {
    if (response?.status && response?.response?.status !== 200) {
      addMessage(response?.response?.data?.detail, "error");
    } else {
      addMessage(response?.message, "error");
    }
    return false;
  }
};
