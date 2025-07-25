import { BASE_URL } from "../constant"
import axios from "axios";
import { getCsrfToken, getSessionId} from "../Hooks/useAxios";

export const  evaluate = async(input1, input2) => {
  try{
    const apiUrl = `${BASE_URL}/evaluate?evaluating_model1=${encodeURIComponent(input1)}&evaluating_model2=${encodeURIComponent(input2)}`;
    const response = await axios.request({
      method: "POST",
      url: apiUrl,
      headers: {
        "Content-Type": "application/json",
        "csrf-token": getCsrfToken(),
        "session-id": getSessionId(), 
      },
    });
    return response.data;
  } catch (error) {
    console.error('API call failed:', error);
    return { error: error.message };
  }
}
export const getEvaluationData = async (agentNames,page = 1,limit = 10) => {
  try {
    let apiUrl = `${BASE_URL}/evaluations?page=${page}&limit=${limit}`;
    if (agentNames) {
      if (Array.isArray(agentNames)) {
        if (agentNames.length > 0) {
          const namesParam = agentNames.map(encodeURIComponent).join(",");
          apiUrl += `&agent_names=${namesParam}`;
        }
      } else if (typeof agentNames === "string" && agentNames.trim() !== "") {
        apiUrl += `&agent_names=${encodeURIComponent(agentNames)}`;
      }
    }
    const response = await axios.request({
      method: "GET",
      url: apiUrl,
      headers: {
        "Content-Type": "application/json",
        "csrf-token": getCsrfToken(),
        "session-id": getSessionId(),
      },
    });
    return response.data;
  } catch (error) {
    console.error('API call failed:', error);
    return { error: error.message };
  }
}
export const getAgentMetricsData = async (agentNames, page = 1, limit = 10) => {
  try {
    let apiUrl = `${BASE_URL}/agent-metrics?page=${page}&limit=${limit}`;
    if (agentNames) {
      if (Array.isArray(agentNames)) {
        if (agentNames.length > 0) {
          const namesParam = agentNames.map(encodeURIComponent).join(",");
          apiUrl += `&agent_names=${namesParam}`;
        }
      } else if (typeof agentNames === "string" && agentNames.trim() !== "") {
        apiUrl += `&agent_names=${encodeURIComponent(agentNames)}`;
      }
    }
    const response = await axios.request({
      method: "GET",
      url: apiUrl,
      headers: {
        "Content-Type": "application/json",
        "csrf-token": getCsrfToken(),
        "session-id": getSessionId(),
      },
    });
    return response.data;
  } catch (error) {
    console.error('API call failed:', error);
    return { error: error.message };
  }
}
export const getToolMetricsData = async (agentNames, page = 1, limit = 10) => {
  try {
    let apiUrl = `${BASE_URL}/tool-metrics?page=${page}&limit=${limit}`;
    if (agentNames) {
      if (Array.isArray(agentNames)) {
        if (agentNames.length > 0) {
          const namesParam = agentNames.map(encodeURIComponent).join(",");
          apiUrl += `&agent_names=${namesParam}`;
        }
      } else if (typeof agentNames === "string" && agentNames.trim() !== "") {
        apiUrl += `&agent_names=${encodeURIComponent(agentNames)}`;
      }
    }
    const response = await axios.request({
      method: "GET",
      url: apiUrl,
      headers: {
        "Content-Type": "application/json",
        "csrf-token": getCsrfToken(),
        "session-id": getSessionId(),
      },
    });
    return response.data;
  } catch (error) {
    console.error('API call failed:', error);
    return { error: error.message };
  }
}

/**
 * Creates a lazy load handler for evaluation data tables
 * @param {String} tabName - The name of the tab ("evaluation", "toolMetric", "agentMetric")
 * @param {Object} tableContainerRef - Reference to the table container element
 * @param {Array} currentData - Current data in the table
 * @param {Function} setData - Function to update data state
 * @param {Number} currentPage - Current page number
 * @param {Function} setPage - Function to update page number
 * @param {Number} limit - Number of items per page
 * @param {String|Array} agentNames - Optional agent names to filter by
 * @param {Function} setIsLoading - Function to update loading state
 * @param {Boolean} hasMore - Whether more data is available (from parent state)
 * @param {Function} setHasMore - Setter to update hasMore in parent
 * @returns {Function} - Scroll event handler function
 */
export const createLazyLoadHandler = (
  tabName,
  tableContainerRef,
  currentData,
  setData,
  currentPage,
  setPage,
  limit,
  agentNames,
  setIsLoading,
  hasMore = true,
  setHasMore = () => {}
) => {
  // Flag to prevent multiple simultaneous fetch calls
  let isFetching = false;

  return async () => {
    // Return early if we're already fetching or parent says no more data
    if (isFetching || !hasMore) {
      return;
    }

    const container = tableContainerRef.current;
    if (!container) {
      return;
    }

    // Calculate if we're near the bottom of the scroll container
    const { scrollTop, scrollHeight, clientHeight } = container;
    const scrollPosition = scrollTop + clientHeight;
    const threshold = scrollHeight - 100; // Increased threshold to 100px
    const isNearBottom = scrollPosition >= threshold;

    if (isNearBottom) {
      isFetching = true;
      setIsLoading(true);

      try {
        // Fetch next page of data
        const nextPage = currentPage + 1;
        let response;
        // Choose the appropriate API based on tab
        if (tabName === "toolMetric") {
          response = await getToolMetricsData(agentNames, nextPage, limit);
        } else if (tabName === "agentMetric") {
          response = await getAgentMetricsData(agentNames, nextPage, limit);
        } else {
          response = await getEvaluationData(agentNames, nextPage, limit);
        }

        // Handle the response based on different possible formats
        if (response && response.data && Array.isArray(response.data) && response.data.length > 0) {
          setData(prevData => [...prevData, ...response.data]);
          setPage(nextPage);
          // If we received fewer items than the limit, we've reached the end
          if (response.data.length < limit) {
            setHasMore(false);
          }
        } else if (response && Array.isArray(response) && response.length > 0) {
          setData(prevData => [...prevData, ...response]);
          setPage(nextPage);
          if (response.length < limit) {
            setHasMore(false);
          }
        } else {
          // No more data to load or invalid response format
          setHasMore(false);
        }
      } catch (error) {
        setHasMore(false);
        console.error("Error fetching more data:", error);
      } finally {
        isFetching = false;
        setIsLoading(false);
      }
    }
  };
};

