const normalizeModelName = (value) => (value || "").trim().toLowerCase();

export const getUnconfiguredCostModels = (response) =>
  Array.isArray(response?.unconfigured_cost_models) ? response.unconfigured_cost_models : [];

export const isUnconfiguredCostModel = (modelName, unconfiguredCostModels = []) => {
  if (!modelName || !Array.isArray(unconfiguredCostModels) || unconfiguredCostModels.length === 0) {
    return false;
  }
  const normalized = normalizeModelName(modelName);
  return unconfiguredCostModels.some((model) => normalizeModelName(model) === normalized);
};
