import React, { useState, useEffect } from 'react';
import styles from './Secret.module.css';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faCopy, faEye, faPlus, faSave, faTrash, faEyeSlash } from '@fortawesome/free-solid-svg-icons';
import { BASE_URL, APIs } from '../../constant';
import Cookies from "js-cookie";
import Toggle from "../commonComponents/Toggle";
import axios from "axios";
import { useRef } from 'react';
import Loader from '../commonComponents/Loader';
import SVGIcons from "../../Icons/SVGIcons";
const SecretKeys = () => {
  const lastRowRef = useRef(null);
  const containerRef = useRef(null);
  const [rows, setRows] = useState([
    { name: '', value: '', isSaved: false, isMasked: false, isUpdated: false }
  ]);
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
const[loading,setLoading]=useState(false)
  useEffect(() => {
    setLoading(true)
    const fetchSecrets = async () => {
      let data;
      let formatted;
      if (activeTab==="Public") {
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

 const saveRow = async (index) => {
  setLoading(true);
  const updatedRows = [...rows];
  const row = updatedRows[index];

  if (!row.name || !row.value) {
    alert('Both fields are required.');
    setLoading(false); 
    return;
  }

  const res = {
    user_email: Cookies.get("email"),
    secret_name: row.name,
    secret_value: row.value,
  };

  try {
    const response = await fetch(`${BASE_URL}${APIs.ADD_SECRET}`, {
      method: "POST",
      headers: {
        accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(res),
    });

    if (!response.ok) throw new Error(`Failed to add secret: ${response.status}`);

    await response.json();
    updatedRows[index].isSaved = true;
    updatedRows[index].isMasked = true;
    setRows(updatedRows);
  } catch (error) {
    console.error("Error saving secret:", error);
    alert("Error saving secret.");
  } finally {
    setLoading(false);
  }
};


  const savePublicRow = async (index) => {
    setLoading(true)
    const updatedRows = [...rows];
    const row = updatedRows[index];

    if (!row.name || !row.value) {
      alert('Both fields are required.');
      return;
    }

    const res = {
      secret_name: row.name,
      secret_value: row.value,
    };

    try {
      const response = await fetch(`${BASE_URL}${APIs.PUBLIC_ADD_SECRET}`, {
        method: "POST",
        headers: {
          accept: "application/json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify(res),
      });

      if (!response.ok) throw new Error(`Failed to add secret: ${response.status}`);

      await response.json();
      updatedRows[index].isSaved = true;
      updatedRows[index].isMasked = true;
      setLoading(false)
      setRows(updatedRows);
    } catch (error) {
      console.error("Error saving secret:", error);
      alert("Error saving secret.");
    }
  };

  const deleteRow = async (index) => {
    setLoading(true)
    const updatedRows = [...rows];
    const rowToDelete = updatedRows[index];

    if (!rowToDelete.isSaved) {
      updatedRows.splice(index, 1);
      setRows(updatedRows);
      return;
    }

    const res = {
      user_email: Cookies.get("email"),
      secret_name: rowToDelete.name,
    };

    try {
      const response = await fetch(`${BASE_URL}${APIs.DELETE_SECRET}`, {
        method: "DELETE",
        headers: {
          accept: "application/json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify(res),
      });

      if (!response.ok) throw new Error(`Failed to delete secret: ${response.status}`);

      await response.json();
      updatedRows.splice(index, 1);
      setLoading(false)
      setRows(updatedRows.length ? updatedRows : [{ name: '', value: '', isSaved: false, isMasked: false, isUpdated: false }]);
    } catch (error) {
      console.error("Error deleting secret:", error);
      alert("Error deleting secret.");
    }
  };

  const deletePublicRow = async (index) => {
    setLoading(true)
    const updatedRows = [...rows];
    const rowToDelete = updatedRows[index];

    if (!rowToDelete.isSaved) {
      updatedRows.splice(index, 1);
      setRows(updatedRows);
      return;
    }

    const res = { secret_name: rowToDelete.name };

    try {
      const response = await fetch(`${BASE_URL}${APIs.PUBLIC_DELETE_SECRET}`, {
        method: "DELETE",
        headers: {
          accept: "application/json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify(res),
      });

      if (!response.ok) throw new Error(`Failed to delete secret: ${response.status}`);

      await response.json();
      updatedRows.splice(index, 1);
      setLoading(false)
      setRows(updatedRows.length ? updatedRows : [{ name: '', value: '', isSaved: false, isMasked: false, isUpdated: false }]);
    } catch (error) {
      console.error("Error deleting secret:", error);
      alert("Error deleting secret.");
    }
  };

  const handleToolInterrupt = (isEnabled) => setIsTool(isEnabled);
  const handleToggle = (e) => {
    handleToolInterrupt(e.target.checked)

  };

  const updateRow = async (index) => {
    setLoading(true)
    const updatedRows = [...rows];
    const row = updatedRows[index];

    if (!row.name || !row.value) {
      alert('Both fields are required.');
      return;
    }

    const res = {
      user_email: Cookies.get("email"),
      secret_name: row.name,
      secret_value: row.value,
    };

    try {
      const response = await fetch(`${BASE_URL}${APIs.UPDATE_SECRET}`, {
        method: "PUT",
        headers: {
          accept: "application/json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify(res),
      });

      if (!response.ok) throw new Error(`Failed to update secret: ${response.status}`);

      await response.json();
      updatedRows[index].isUpdated = false;
      updatedRows[index].isMasked = true;
      setLoading(false)
      setRows(updatedRows);
    } catch (error) {
      console.error("Error updating secret:", error);
      alert("Error updating secret.");
    }
  };

  const updatePublicRow = async (index) => {
    console.log("hiii");
    
    setLoading(true)
    const updatedRows = [...rows];
    const row = updatedRows[index];

    if (!row.name || !row.value) {
      alert('Both fields are required.');
      return;
    }

    const res = {
      secret_name: row.name,
      secret_value: row.value,
    };

    try {
      const response = await fetch(`${BASE_URL}${APIs.PUBLIC_UPDATE_SECRET}`, {
        method: "PUT",
        headers: {
          accept: "application/json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify(res),
      });

      if (!response.ok) throw new Error(`Failed to update secret: ${response.status}`);

      await response.json();
      updatedRows[index].isUpdated = false;
      updatedRows[index].isMasked = true;
      setLoading(false)
      setRows(updatedRows);
    } catch (error) {
      console.error("Error updating secret:", error);
      alert("Error updating secret.");
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

       if (copy === "copy") {
        await navigator.clipboard.writeText(secretValue);
        alert("Secret value copied to clipboard!");
      } else {
        const updatedRows = [...rows];
        updatedRows[index].value = secretValue;
        updatedRows[index].isMasked = false;
        setRows(updatedRows);
      }

    } else {
      alert("Failed to retrieve secret value");
    }
  } catch (error) {
    console.error("Error fetching secret value:", error);
    alert("Error fetching secret value.");
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

       if (copy === "copy") {
        await navigator.clipboard.writeText(secretValue);
        alert("Secret value copied to clipboard!");
      } else {
        const updatedRows = [...rows];
        updatedRows[index].value = secretValue;
        updatedRows[index].isMasked = false;
        setRows(updatedRows);
      }
    } else {
      alert("Failed to retrieve secret value");
    }
  } catch (error) {
    console.error("Error fetching secret value:", error);
    alert("Error fetching secret value.");
  } finally {
    setLoading(false);
  }
};

  const toggleMask = (index) => {
    const updatedRows = [...rows];
    updatedRows[index].isMasked = !updatedRows[index].isMasked;
    setRows(updatedRows);
  };

  const copyValue = (value) => {
    navigator.clipboard.writeText(value);
    alert('Value copied to clipboard!');
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
    {loading && <Loader /> }
    <div className={styles.container}>
        <div className={styles.plusIcons}>
          <h6 className={styles.titleCss}>LIST OF SECRETS</h6>
   <span
  className={styles.addIcon}
  onClick={rows.some(row => !row.isSaved) ? null : addRow}
  style={{ opacity: rows.some(row => !row.isSaved) ? 0.5 : 1, cursor: rows.some(row => !row.isSaved) ? 'not-allowed' : 'pointer' }}
  title={rows.some(row => !row.isSaved) ? "Please save the current secret before adding another." : "Add Secret"}
>
 <button  className={styles.plus}>
            <SVGIcons icon="fa-plus" fill="#007CC3" width={16} height={16} />
            <label className={styles.addSecret}>Add Secret</label>
          </button>
  {/* <span className={styles.addSecret}>Add Secret</span> */}
</span>
 </div>
    {/* <span className={styles.publicCss}>
      <Toggle onChange={handleToggle} value={isTool} />
    </span>
    <label className={styles.privateCss}>{isTool ? 'Public' : 'Private'}</label> */}
     <div style={{ marginLeft: 40 }}>
          <button
            className={activeTab === "Private" ? styles.activeTab : styles.tab}
            onClick={() => setActiveTab("Private")}
          >
            Private
          </button>
          <button
            className={activeTab === "Public" ? styles.activeTab : styles.tab}
            onClick={() => setActiveTab("Public")}
          >
            Public
          </button>
        </div>
      
<div className={styles.secretCss} ref={containerRef}>
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



            {canShowIcons && !row.isSaved && (
              <span className={styles.iconCss} title="Save" onClick={() => activeTab === "Private" ? saveRow(index) : savePublicRow(index)}>
                {/* <FontAwesomeIcon icon={faSave} /> */}
                {/* <button>Save</button> */}
                <button class="Secret_activeTab__eHq+E">Save</button>
              </span>
            )}

            {row.isSaved && row.isUpdated && (
              <span className={styles.iconCss} title="Update" onClick={() => activeTab === "Private" ? updateRow(index) : updatePublicRow(index)}>
                {/* <button>Update</button> */}
                <button class="Secret_activeTab__eHq+E">Update</button>

              </span>
            )}

            <>
              <span className={`${styles.iconCss} ${styles.iconDelete}`}title="Delete" onClick={() => activeTab === "Private" ? deleteRow(index) : deletePublicRow(index)}>
                <FontAwesomeIcon icon={faTrash} />
              </span>
              {/* <span className={styles.iconCss} title="Toggle View" onClick={() => !isTool? getEyeSecrets(row.name,index):getPublicSecrets(row.name,index)}>
                <FontAwesomeIcon icon={faEye} />
              </span> */}
              <span
               className={`${styles.iconCss} ${styles.iconEye}`}
                title={row.isMasked ? "Show Secret" : "Hide Secret"}
                onClick={() => {
                  if (row.isMasked) {
                    activeTab === "Private" ? getEyeSecrets(row.name, index,"") : getPublicSecrets(row.name, index,"");
                  } else {
                    toggleMask(index); // hide again
                  }
                }}
              >
                <FontAwesomeIcon icon={row.isMasked ? faEye : faEyeSlash} />
              </span>
              <span className={`${styles.iconCss} ${styles.iconCopy}`}title="Copy Value" onClick={() =>activeTab === "Private" ? getEyeSecrets(row.name, index,"copy") : getPublicSecrets(row.name, index,"copy")}>
                <FontAwesomeIcon icon={faCopy} />
              </span>
            </>
          </div>
        );
      })}
    </div>
    </div>
    </>
  );
};

export default SecretKeys;
