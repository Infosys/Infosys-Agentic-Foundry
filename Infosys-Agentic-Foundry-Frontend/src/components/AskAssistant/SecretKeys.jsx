import React, { useState, useEffect } from 'react';
import styles from './Secret.module.css';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faCopy, faEye, faPlus, faSave, faTrash, faEyeSlash, faTimes } from '@fortawesome/free-solid-svg-icons';
import { BASE_URL, APIs } from '../../constant';
import Cookies from "js-cookie";
import Toggle from "../commonComponents/Toggle";
import axios from "axios";
import { useRef } from 'react';
import Loader from '../commonComponents/Loader';
import SVGIcons from "../../Icons/SVGIcons";
import { useMessage } from '../../Hooks/MessageContext';
const SecretKeys = () => {
  const lastRowRef = useRef(null);
  const containerRef = useRef(null);
  const role = Cookies.get("role");
 const { addMessage} = useMessage();
  const [rows, setRows] = useState([
    { name: '', value: '', isSaved: false, isMasked: false, isUpdated: false }
  ]);
  const isGuestWithEmptyRows = role?.toUpperCase() === "GUEST" &&
  rows.every(row => !row.name && !row.value && !row.isSaved);
  const [activeTab, setActiveTab] = useState("Private");
  const [shouldScroll, setShouldScroll] = useState(false);
  useEffect(() => {
    if (shouldScroll && containerRef.current) {
      containerRef.current.scrollTo({
        top: containerRef.current.scrollHeight,
        behavior: 'smooth',
      });
      setShouldScroll(false); // Reset the scroll flag
    }
  }, [rows, shouldScroll]);

  const [isTool, setIsTool] = useState(false);
  const [loading, setLoading] = useState(false)
  useEffect(() => {
    setLoading(true)
    const fetchSecrets = async () => {
      let data;
      let formatted;
      if (activeTab === "Public") {
        data = await getPublicScripts()
        formatted = Array.isArray(data)
          ? data.map((item) => ({
            name: item.name || '',
            value: '', // Update this if you have actual secret values
            isSaved: true,
            isMasked: true,
            isUpdated: false,
          }))
          : [];
      } else {
        data = await getScripts()
        const secretsObj = data || {};

        formatted = Object.entries(secretsObj).map(([key, value]) => ({
          name: value,
          value: "",
          isSaved: true,
          isMasked: true,
          isUpdated: false,
        }));
      }
      setRows(formatted.length ? formatted : [{
        name: '', value: '', isSaved: false, isMasked: false, isUpdated: false
      }]);
      setLoading(false)
    };

    fetchSecrets();
  }, [activeTab]);

  useEffect(() => {
    const checkHealth = async () => {
      try {
        const res = await fetch(`${BASE_URL}${APIs.HEALTH_SECRETS}`);
        if (!res.ok) throw new Error('API Unhealthy');
      } catch (err) {
        console.error("API health check failed:", err);
      }
    };

    checkHealth();
  }, []);
  const isRowComplete = (row) => row.name.trim() !== '' && row.value.trim() !== '';

  const handleInputChange = (index, field, value) => {
    const updatedRows = [...rows];
    updatedRows[index][field] = value;
    if (updatedRows[index].isSaved) {
      updatedRows[index].isUpdated = true;
    }
    setRows(updatedRows);
  };

  const addRow = () => {
    setRows(prevRows => {
      const newRows = [...prevRows, { name: '', value: '', isSaved: false, isMasked: false, isUpdated: false }];
      return newRows;
    });
    setShouldScroll(true);
  };
  if (role?.toUpperCase() !== 'GUEST' && rows.length === 0) {
  setRows([{ name: '', value: '', isSaved: false, isMasked: true }]);
}
  const saveRow = async (index) => {
  setLoading(true);
  const updatedRows = [...rows];
  const row = updatedRows[index];

  if (!row.name || !row.value) {
    addMessage('Both fields are required.',"error");
    setLoading(false);
    return;
  }

  const res = {
    user_email: Cookies.get("email"),
    secret_name: row.name,
    secret_value: row.value,
  };

  let response;
  try {
    response = await fetch(`${BASE_URL}${APIs.ADD_SECRET}`, {
      method: "POST",
      headers: {
        accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(res),
    });
    if (response.status === 500) {
      const errorData = await response.json();
      addMessage(errorData.detail || "Internal Server Error", "error");
      setLoading(false);
      return;
    }
    if (!response.ok) {
      throw new Error(`Failed to add secret: ${response.status}`);
    }

    await response.json();
    updatedRows[index].isSaved = true;
    updatedRows[index].isMasked = true;
    setRows(updatedRows);
  } catch (error) {
    console.error("Error saving secret:", response);
    addMessage("Error saving secret", "error");
  } finally {
    setLoading(false);
  }
};


 const savePublicRow = async (index) => {
  setLoading(true)
  const updatedRows = [...rows];
  const row = updatedRows[index];

  if (!row.name || !row.value) {
    addMessage('Both fields are required.', "error");
    setLoading(false);
    return;
  }

  const res = {
    secret_name: row.name,
    secret_value: row.value,
  };

  let response;
  try {
    response = await fetch(`${BASE_URL}${APIs.PUBLIC_ADD_SECRET}`, {
      method: "POST",
      headers: {
        accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(res),
    });

    if (response.status === 500) {
      const errorData = await response.json();
      addMessage(errorData.detail || "Internal Server Error", "error");
      setLoading(false);
      return;
    }

    if (!response.ok) {
      throw new Error(`Failed to add public secret: ${response.status}`);
    }

    await response.json();
    updatedRows[index].isSaved = true;
    updatedRows[index].isMasked = true;
    setRows(updatedRows);
  } catch (error) {
    console.error("Error saving public secret:", error);
    addMessage("Error saving secret.","error");
  } finally {
    setLoading(false);
  }
};

 const deleteRow = async (index) => {
  setLoading(true);
  const updatedRows = [...rows];
  const rowToDelete = updatedRows[index];

  if (!rowToDelete.isSaved) {
    updatedRows.splice(index, 1);
    setRows(updatedRows);
    setLoading(false);
    return;
  }

  const res = {
    user_email: Cookies.get("email"),
    secret_name: rowToDelete.name,
  };

  let response;
  try {
    response = await fetch(`${BASE_URL}${APIs.DELETE_SECRET}`, {
      method: "DELETE",
      headers: {
        accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(res),
    });

    if (response.status === 500) {
      const errorData = await response.json();
      addMessage(errorData.detail || "Internal Server Error", "error");
      return;
    }

    if (!response.ok) {
      throw new Error(`Failed to delete secret: ${response.status}`);
    }

    await response.json();
    updatedRows.splice(index, 1);
    setRows(
      updatedRows.length
        ? updatedRows
        : [{ name: '', value: '', isSaved: false, isMasked: false, isUpdated: false }]
    );
  } catch (error) {
    console.error("Error deleting secret:", error);
    addMessage("Error deleting secret.","error");
  } finally {
    setLoading(false);
  }
};

const deletePublicRow = async (index) => {
  setLoading(true);
  const updatedRows = [...rows];
  const rowToDelete = updatedRows[index];

  if (!rowToDelete.isSaved) {
    updatedRows.splice(index, 1);
    setRows(updatedRows);
    setLoading(false);
    return;
  }

  const res = { secret_name: rowToDelete.name };

  let response;
  try {
    response = await fetch(`${BASE_URL}${APIs.PUBLIC_DELETE_SECRET}`, {
      method: "DELETE",
      headers: {
        accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(res),
    });

    if (response.status === 500) {
      const errorData = await response.json();
      addMessage(errorData.detail || "Internal Server Error", "error");
      return;
    }

    if (!response.ok) {
      throw new Error(`Failed to delete secret: ${response.status}`);
    }

    await response.json();
    updatedRows.splice(index, 1);
    setRows(
      updatedRows.length
        ? updatedRows
        : [{ name: '', value: '', isSaved: false, isMasked: false, isUpdated: false }]
    );
  } catch (error) {
    console.error("Error deleting secret:", error);
    addMessage("Error deleting secret.", "error");
  } finally {
    setLoading(false);
  }
};

  const handleToolInterrupt = (isEnabled) => setIsTool(isEnabled);
  const handleToggle = (e) => {
    handleToolInterrupt(e.target.checked)

  };

 const updateRow = async (index) => {
  setLoading(true);
  const updatedRows = [...rows];
  const row = updatedRows[index];

  if (!row.name || !row.value) {
    addMessage('Both fields are required.', "error");
    setLoading(false);
    return;
  }

  const res = {
    user_email: Cookies.get("email"),
    secret_name: row.name,
    secret_value: row.value,
  };

  let response;
  try {
    response = await fetch(`${BASE_URL}${APIs.UPDATE_SECRET}`, {
      method: "PUT",
      headers: {
        accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(res),
    });

    if (response.status === 500) {
      const errorData = await response.json();
      addMessage(errorData.detail || "Internal Server Error", "error");
      return;
    }

    if (!response.ok) {
      throw new Error(`Failed to update secret: ${response.status}`);
    }

    await response.json();
    updatedRows[index].isUpdated = false;
    updatedRows[index].isMasked = true;
    setRows(updatedRows);
  } catch (error) {
    console.error("Error updating secret:", error);
    addMessage("Error updating secret.", "error");
  } finally {
    setLoading(false);
  }
};


 const updatePublicRow = async (index) => {
  setLoading(true);
  const updatedRows = [...rows];
  const row = updatedRows[index];

  if (!row.name || !row.value) {
    addMessage('Both fields are required.', "error");
    setLoading(false);
    return;
  }

  const res = {
    secret_name: row.name,
    secret_value: row.value,
  };

  let response;
  try {
    response = await fetch(`${BASE_URL}${APIs.PUBLIC_UPDATE_SECRET}`, {
      method: "PUT",
      headers: {
        accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(res),
    });

    if (response.status === 500) {
      const errorData = await response.json();
      addMessage(errorData.detail || "Internal Server Error", "error");
      return;
    }

    if (!response.ok) {
      throw new Error(`Failed to update public secret: ${response.status}`);
    }

    await response.json();
    updatedRows[index].isUpdated = false;
    updatedRows[index].isMasked = true;
    setRows(updatedRows);
  } catch (error) {
    console.error("Error updating public secret:", error);
    addMessage("Error updating secret.", "error");
  } finally {
    setLoading(false);
  }
};

  const getEyeSecrets = async (name, index, copy) => {
    setLoading(true);
    try {
      const apiUrl = `${BASE_URL}${APIs.SECRETS_GET}`;
      const payload = {
        user_email: Cookies.get('email'),
        secret_name: name,
      };

      const response = await axios.post(apiUrl, payload, {
        headers: { "Content-Type": "application/json" },
      });

      if (response?.status === 200) {
        const secretValue = response.data.secret_value || '';
        const updatedRows = [...rows];
        if (copy === "copy") {
          updatedRows[index].isMasked = false
          updatedRows[index].value = secretValue;
          setRows(updatedRows);
          await navigator.clipboard.writeText(secretValue);
          addMessage("Secret value copied to clipboard!","success");

        } else {
          updatedRows[index].value = secretValue;
          updatedRows[index].isMasked = false;
          setRows(updatedRows);
        }

      } else {
        addMessage("Failed to retrieve secret value","error");
      }
    } catch (error) {
      console.error("Error fetching secret value:", error);
      addMessage("Error fetching secret value.","error");
    } finally {
      setLoading(false);
    }
  };




  const getPublicSecrets = async (name, index, copy) => {
    setLoading(true);
    try {
      const apiUrl = `${BASE_URL}${APIs.PUBLIC_SECRETS_GET}`;
      const payload = { secret_name: name };

      const response = await axios.post(apiUrl, payload, {
        headers: { "Content-Type": "application/json" },
      });

      if (response?.status === 200) {
        const secretValue = response.data.key_value || '';
        const updatedRows = [...rows];
        if (copy === "copy") {
          updatedRows[index].isMasked = false
          updatedRows[index].value = secretValue;
          setRows(updatedRows);
          await navigator.clipboard.writeText(secretValue);
           addMessage("Secret value copied to clipboard!","success")
        } else {
          const updatedRows = [...rows];
          updatedRows[index].value = secretValue;
          updatedRows[index].isMasked = false;
          setRows(updatedRows);
        }
      } else {
        addMessage("Failed to retrieve secret value","error");
      }
    } catch (error) {
      console.error("Error fetching secret value:", error);
      addMessage("Error fetching secret value.","error");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    if (role && role.toUpperCase() === "GUEST") {
      setActiveTab("Public");
    }
  }, [role]);

  const toggleMask = (index) => {
    const updatedRows = [...rows];
    updatedRows[index].isMasked = !updatedRows[index].isMasked;
    setRows(updatedRows);
  };

  const copyValue = (value) => {
    navigator.clipboard.writeText(value);
    addMessage('Value copied to clipboard!');
  };

  const getScripts = async () => {
    setLoading(true)
    try {
      const apiUrl = `${BASE_URL}${APIs.GET_SECRETS}`;
      const payload = {
        user_email: Cookies.get('email')
      }
      const response = await axios.post(apiUrl, payload, {
        headers: {
          "Content-Type": "application/json",
        },
      });

      if (response?.status === 200) {
        setLoading(false)
        setRows(response.data.secret_names.length ? response.data.secret_names : [{ name: '', value: '', isSaved: false, isMasked: false, isUpdated: false }]);

        // setRows(response.data.secrets)
        return response.data.secret_names;
      } else {
        return null;
      }
    } catch (error) {
      console.error("Error fetching secrets:", error);
      return null;
    }
  };
  const getPublicScripts = async () => {
    setLoading(true)
    try {
      const apiUrl = `${BASE_URL}${APIs.GET_PUBLIC_SECRETS}`;

      const response = await axios.post(apiUrl, {
        headers: {
          "Content-Type": "application/json",
        },
      });

      if (response?.status === 200) {
        setLoading(false)
        setRows(response.data.public_key_names.length ? response.data.public_key_names : [{ name: '', value: '', isSaved: false, isMasked: false, isUpdated: false }]);

        // setRows(response.data.secrets)
        return response.data.public_key_names;
      } else {
        return null;
      }
    } catch (error) {
      console.error("Error fetching secrets:", error);
      return null;
    }
  }

  return (
    <>
      {loading && <Loader />}
      <div className={styles.container}>
        <div className={styles.plusIcons}>
          <h6 className={styles.titleCss}>LIST OF VAULT SECRET</h6>
          <span
            className={styles.addIcon}
            onClick={
              rows.some(row => !row.isSaved) || (role && role.toUpperCase() === "GUEST")
                ? null
                : addRow
            }
            style={{
              opacity: rows.some(row => !row.isSaved) || (role && role.toUpperCase() === "GUEST") ? 0.5 : 1,
              cursor: rows.some(row => !row.isSaved) || (role && role.toUpperCase() === "GUEST") ? 'not-allowed' : 'pointer',
            }}
            title={
              rows.some(row => !row.isSaved)
                ? "Please save the current secret before adding another."
                : (role && role.toUpperCase() === "GUEST"
                  ? "Guests cannot add secrets."
                  : "Add Secret")
            }
          >
            <button className={styles.plus} disabled={role && role.toUpperCase() === "GUEST"}>
              <SVGIcons icon="fa-plus" fill="#007CC3" width={16} height={16} />
              <label className={styles.addSecret}>Add Secret</label>
            </button>
          </span>

        </div>
        {/* <span className={styles.publicCss}>
      <Toggle onChange={handleToggle} value={isTool} />
    </span>
    <label className={styles.privateCss}>{isTool ? 'Public' : 'Private'}</label> */}
        <div style={{ marginLeft: 40 }}>
          {role && role.toUpperCase() !== "GUEST" && (
            <button
              className={activeTab === "Private" ? styles.activeTab : styles.tab}
              onClick={() => setActiveTab("Private")}
            >
              Private
            </button>
          )}

          <button
            className={activeTab === "Public" ? styles.activeTab : styles.tab}
            onClick={() => setActiveTab("Public")}
          >
            Public
          </button>
        </div>

        <div className={styles.secretCss} ref={containerRef}>
          {rows.length === 0 && role.toUpperCase() ==="GUEST" ?(
            <>
            <div className={styles.noSecretsMessage}>
              There are no secrets to display
            </div>
            </>
          ):(
            <>
             {rows.map((row, index) => {
            const canShowIcons = isRowComplete(row);
            const isLast = index === rows.length - 1;
            return (
              <div className={styles.row} key={index} ref={isLast ? lastRowRef : null}>
                <input
                  type="text"
                  value={row.name}
                  placeholder="Enter Name"
                  onChange={(e) => handleInputChange(index, 'name', e.target.value)}
                  className={styles.input}
                  disabled={row.isSaved && row.isMasked}
                />

                <textarea
                  value={row.isSaved && row.isMasked ? '.......' : row.value}
                  placeholder="Enter Value"
                  onChange={(e) => handleInputChange(index, 'value', e.target.value)}
                  className={`${styles.input} ${styles.valueTextarea}`}
                  disabled={row.isSaved && row.isMasked}
                />



               {canShowIcons && !row.isSaved && role?.toUpperCase() !== 'GUEST' && (
  <span
    className={styles.iconCss}
    title="Save"
    onClick={() =>
      activeTab === "Private" ? saveRow(index) : savePublicRow(index)
    }
  >
    <button className={styles.activeTab}>Save</button>
  </span>
)}

{row.isSaved && row.isUpdated && role?.toUpperCase() !== 'GUEST' && (
  <span
    className={styles.iconCss}
    title="Update"
    onClick={() =>
      activeTab === "Private" ? updateRow(index) : updatePublicRow(index)
    }
  >
    <button className={styles.activeTab}>Update</button>
  </span>
)}


                <>
              <span
  className={`${styles.iconCss} ${styles.iconDelete}`}
  title={
    !row.isSaved
      ? "Save the secret before you can delete it."
      : role && role.toUpperCase() === "GUEST"
      ? "Guests are not allowed to delete secrets."
      : "Delete"
  }
  onClick={() => {
    if (!row.isSaved || (role && role.toUpperCase() === "GUEST")) return;
    activeTab === "Private" ? deleteRow(index) : deletePublicRow(index);
  }}
  style={{
    opacity:
      !row.isSaved || (role && role.toUpperCase() === "GUEST") ? 0.5 : 1,
    cursor:
      !row.isSaved || (role && role.toUpperCase() === "GUEST")
        ? "not-allowed"
        : "pointer",
  }}
>
  <FontAwesomeIcon icon={faTrash} />
</span>

                 {/* Show / Hide Secret */}
<span
  className={`${styles.iconCss} ${styles.iconEye}`}
  title={
    !row.isSaved
      ? "Save the secret first to view it."
      : role && role.toUpperCase() === "GUEST"
      ? "Guests are not allowed to view secrets."
      : row.isMasked
      ? "Show Secret"
      : "Hide Secret"
  }
  onClick={
    !row.isSaved || (role && role.toUpperCase() === "GUEST")
      ? null
      : () => {
          if (row.isMasked) {
            activeTab === "Private"
              ? getEyeSecrets(row.name, index, "")
              : getPublicSecrets(row.name, index, "");
          } else {
            toggleMask(index);
          }
        }
  }
  style={{
    opacity:
      !row.isSaved || (role && role.toUpperCase() === "GUEST") ? 0.5 : 1,
    cursor:
      !row.isSaved || (role && role.toUpperCase() === "GUEST")
        ? "not-allowed"
        : "pointer",
  }}
>
  <FontAwesomeIcon icon={row.isMasked ? faEye : faEyeSlash} />
</span>

{/* Copy Secret */}
{/* <span
  className={`${styles.iconCss} ${styles.iconCopy}`}
  title={
    !row.isSaved
      ? "Save the secret first to copy it."
      : role && role.toUpperCase() === "GUEST"
      ? "Guests are not allowed to copy secrets."
      : "Copy Value"
  }
  onClick={
    !row.isSaved || (role && role.toUpperCase() === "GUEST")
      ? null
      : () =>
          activeTab === "Private"
            ? getEyeSecrets(row.name, index, "copy")
            : getPublicSecrets(row.name, index, "copy")
  }
  style={{
    opacity:
      !row.isSaved || (role && role.toUpperCase() === "GUEST") ? 0.5 : 1,
    cursor:
      !row.isSaved || (role && role.toUpperCase() === "GUEST")
        ? "not-allowed"
        : "pointer",
  }}
>
  <FontAwesomeIcon icon={faCopy} />
</span> */}
 {index === rows.length - 1 && !row.isSaved && (
      <span
        className={styles.iconClose} // create this in CSS for styling close icon
        title="Remove this secret"
        onClick={() => {
          const newRows = [...rows];
          newRows.pop();  // remove last row
          setRows(newRows);
        }}
        style={{ cursor: "pointer", color: "#333", marginLeft: "10px" }}
      >
        <FontAwesomeIcon icon={faTimes} />
      </span>
    )}

                </>
              </div>
            );
          })}
            </>
          )}
         
        </div>
        {role.toUpperCase() !=="GUEST" &&(
          <>
              <div className={styles?.cssForText}>
          Access your secret keys in Python via:
        </div>
          <div className={styles?.cssForcode}>
<pre
  style={{
    backgroundColor: '#2d2d2d',
    color: '#f8f8f2',
    padding: '16px',
    borderRadius: '6px',
    marginTop: '20px',
    fontSize: '14px',
    overflowX: 'auto',
    lineHeight: '1.5',
    whiteSpace: 'pre-wrap',
    marginLeft: '40px',
    marginRight: '40px',
  }}
>
<code>
{`# Example: Using user and public secrets to build a secure API request URL

def fetch_weather(city):
    api_key = get_user_secrets('weather_api_key', 'no_api_key_found')
    base_url = get_public_secrets('weather_api_base_url', 'https://default-weather-api.com')
    full_url = f"{base_url}/weather?city={city}&apikey={api_key}"
    return f"Ready to fetch data from: {full_url}"

print(fetch_weather("New York"))`}
</code>
</pre>

</div>
          </>
        )}

      </div>
    </>
  );
};

export default SecretKeys;
