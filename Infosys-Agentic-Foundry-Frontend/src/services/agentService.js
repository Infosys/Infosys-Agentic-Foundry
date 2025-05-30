import axios from "axios";
import { BASE_URL } from "../constant";

let getMethod = "GET";

export const getAgentsByPageLimit = async ({ page, limit }) => {
  try {
    const apiUrl = `${BASE_URL}/get-agents-by-pages/${page}?limit=${limit}`;
    const response = await axios.request({
      method: getMethod,
      url: apiUrl,
      headers: {
        "Content-Type": "application/json",
      },
    });
    console.log(response);
    if (response?.status === 200) {
      return response?.data;
    } else {
      return null;
    }
  } catch (error) {
    return null;
  }
};
