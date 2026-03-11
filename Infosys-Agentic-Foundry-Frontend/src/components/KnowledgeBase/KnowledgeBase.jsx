import { useMemo, useState, useEffect, useCallback, useRef } from "react";
import Cookies from "js-cookie";
import SubHeader from "../commonComponents/SubHeader.jsx";
import styles from "./KnowledgeBase.module.css";
import { useMessage } from "../../Hooks/MessageContext";
import Loader from "../commonComponents/Loader.jsx";
import useFetch from "../../Hooks/useAxios.js";
import { APIs } from "../../constant";
import { useToolsAgentsService } from "../../services/toolService.js";
import { useKnowledgeBaseService } from "../../services/knowledgeBaseService.js";
import DisplayCard1 from "../../iafComponents/GlobalComponents/DisplayCard/DisplayCard1.jsx";
import { useErrorHandler } from "../../Hooks/useErrorHandler";
import EmptyState from "../commonComponents/EmptyState.jsx";
import SummaryLine from "../../iafComponents/GlobalComponents/SummaryLine.jsx";
import KnowledgeBaseForm from "./KnowledgeBaseForm.jsx";
import { useActiveNavClick } from "../../events/navigationEvents";

// Layout constants for card calculation
const CARD_MIN_WIDTH = 200;
const CARD_HEIGHT = 75;
const CARD_GAP = 16;
const DEBOUNCE_DELAY = 300;

export default function KnowledgeBase() {
  const { calculateDivs } = useToolsAgentsService();
  const { deleteKnowledgeBases } = useKnowledgeBaseService();
  const { fetchData } = useFetch();
  const { addMessage } = useMessage();
  const { handleError, handleApiError, handleApiSuccess } = useErrorHandler();

  // User info
  const loggedInUserEmail = Cookies.get("email");

  // State
  const [loading, setLoading] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");
  const [visibleData, setVisibleData] = useState([]);
  const [totalCount, setTotalCount] = useState(0);
  // Form modal state
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [showUpdateForm, setShowUpdateForm] = useState(false);
  const [editKbData, setEditKbData] = useState(null);

  // Refs
  const pageRef = useRef(1);
  const listContainerRef = useRef(null);
  const isLoadingRef = useRef(false);
  const hasLoadedOnce = useRef(false);

  // Map knowledge base data from API response
  const mapKBData = useCallback((kb) => {
    const raw = kb || {};
    return {
      id: raw.kb_id,
      kb_id: raw.kb_id,
      name: raw.kb_name || "Unnamed Knowledge Base",
      documents: raw.list_of_documents || [],
      created_by: raw.created_by || "",
      created_on: raw.created_on || "",
      is_public: raw.is_public || false,
      shared_with_departments: raw.shared_with_departments || [],
      raw: raw,
    };
  }, []);

  // Fetch knowledge bases from API
  const getKnowledgeBases = useCallback(
    async () => {
      if (isLoadingRef.current) return [];
      isLoadingRef.current = true;
      setLoading(true);

      try {
        const response = await fetchData(APIs.KB_GET_LIST);
        const knowledgeBases = response?.knowledge_bases || [];

        let filteredData = knowledgeBases;

        // Apply search filter
        if (searchTerm.trim()) {
          filteredData = filteredData.filter((kb) =>
            kb.kb_name?.toLowerCase().includes(searchTerm.toLowerCase())
          );
        }

        const mappedData = filteredData.map(mapKBData);

        setVisibleData(mappedData);
        setTotalCount(response?.count || mappedData.length);

        return mappedData;
      } catch (error) {
        handleError(error, { context: "KnowledgeBase.getKnowledgeBases" });
        setVisibleData([]);
        return [];
      } finally {
        setLoading(false);
        isLoadingRef.current = false;
      }
    },
    [mapKBData, searchTerm, handleError, fetchData]
  );

  // Handle search
  const handleSearch = async (searchValue) => {
    setSearchTerm(searchValue || "");
    pageRef.current = 1;
    setVisibleData([]);
    setLoading(true);

    try {
      const response = await fetchData(APIs.KB_GET_LIST);
      const knowledgeBases = response?.knowledge_bases || [];

      let filteredData = knowledgeBases;

      // Apply search filter
      if (searchValue?.trim()) {
        filteredData = filteredData.filter((kb) =>
          kb.kb_name?.toLowerCase().includes(searchValue.toLowerCase())
        );
      }

      const mappedData = filteredData.map(mapKBData);

      setVisibleData(mappedData);
      setTotalCount(mappedData.length);
    } catch (error) {
      handleError(error, { context: "KnowledgeBase.handleSearch" });
      setVisibleData([]);
    } finally {
      setLoading(false);
    }
  };

  // Initial load - runs only once on mount
  useEffect(() => {
    if (hasLoadedOnce.current) return;
    hasLoadedOnce.current = true;
    pageRef.current = 1;
    getKnowledgeBases();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Clear search
  const clearSearch = () => {
    setSearchTerm("");
    setVisibleData([]);
    setTimeout(() => {
      pageRef.current = 1;
      getKnowledgeBases();
    }, DEBOUNCE_DELAY);
  };

  // Refresh
  const handleRefreshClick = async () => {
    try {
      setSearchTerm("");
      setVisibleData([]);
      pageRef.current = 1;
      await getKnowledgeBases();
    } catch (e) {
      // swallow
    }
  };

  // Handle create new
  const handleCreateClick = () => {
    setShowCreateForm(true);
  };

  // Handle form close
  const handleFormClose = () => {
    setShowCreateForm(false);
  };

  // Handle form save (refresh list after create)
  const handleFormSave = () => {
    getKnowledgeBases();
  };

  // Handle card click - open update form with card data (same pattern as Tools)
  const handleCardClick = (_name, item) => {
    setEditKbData(item);
    setShowUpdateForm(true);
  };

  // Handle update form close
  const handleUpdateFormClose = () => {
    setShowUpdateForm(false);
    setEditKbData(null);
  };

  // Handle update form save (refresh list after update)
  const handleUpdateFormSave = () => {
    setShowUpdateForm(false);
    setEditKbData(null);
    getKnowledgeBases();
  };

  // Handle delete
  const handleDeleteClick = async (name, item) => {
    try {
      const response = await deleteKnowledgeBases([item.kb_id || item.id], loggedInUserEmail);

      // Check if any KBs failed to delete (error is in failed_kbs array)
      if (response?.failed_kbs?.length > 0) {
        const failedKb = response.failed_kbs[0];
        const errorMsg = typeof failedKb?.error === "string"
          ? failedKb.error
          : "Failed to delete knowledge base. It may be in use by an application.";
        addMessage(errorMsg, "error");
        return;
      }

      handleApiSuccess(response, {
        fallbackMessage: `Knowledge Base "${item.name}" deleted successfully`,
      });

      // Refresh the list
      getKnowledgeBases();
    } catch (error) {
      // Check if backend returned failed_kbs structure in error response (400 status)
      const failedKbs = error?.response?.data?.detail?.failed_kbs || error?.response?.data?.failed_kbs;

      if (failedKbs?.length > 0) {
        const failedKb = failedKbs[0];
        const errorMsg = typeof failedKb?.error === "string"
          ? failedKb.error
          : "Failed to delete knowledge base. It may be in use by an application.";
        addMessage(errorMsg, "error");
        return;
      }

      handleApiError(error, { context: "KnowledgeBase.handleDeleteClick" });
    }
  };

  // Visible data
  const visible = useMemo(() => {
    return visibleData;
  }, [visibleData]);

  useActiveNavClick("/knowledge-base", () => {
    setShowCreateForm(false);
    setShowUpdateForm(false);
    setEditKbData(null);
  });

  return (
    <>
      {loading && <Loader />}

      <div className={"pageContainer"}>
        <SubHeader
          heading={"Knowledge Base"}
          activeTab={"knowledgebase"}
          onSearch={handleSearch}
          searchValue={searchTerm}
          clearSearch={clearSearch}
          handleRefresh={handleRefreshClick}
          onPlusClick={handleCreateClick}
          plusButtonLabel="New Knowledge Base"
          reverseButtons={true}
        />

        <SummaryLine visibleCount={visible.length} totalCount={totalCount} />

        <div className="listWrapper" ref={listContainerRef} aria-label="Knowledge Base list scrollable container">
          {visible?.length > 0 && (
            <DisplayCard1
              data={visible}
              onCardClick={handleCardClick}
              onDeleteClick={handleDeleteClick}
              onCreateClick={handleCreateClick}
              showDeleteButton={true}
              showButton={false}
              showCreateCard={false}
              enableComplexDelete={false}
              cardNameKey="name"
              cardOwnerKey="created_by"
              emptyMessage="No knowledge bases found"
              contextType="knowledge base"
              className={styles.kbCardsGrid}
              isUnusedSection={true}
            />
          )}

          {/* Display EmptyState when filters are active but no results */}
          {searchTerm.trim() && visible.length === 0 && !loading && (
            <EmptyState
              filters={[
                ...(searchTerm.trim() ? [`Search: ${searchTerm}`] : []),
              ]}
              onClearFilters={() => {
                setSearchTerm("");
                handleRefreshClick();
              }}
              onCreateClick={handleCreateClick}
              createButtonLabel="New Knowledge Base"
            />
          )}

          {/* Display EmptyState when no data exists from backend (no filters applied) */}
          {!searchTerm.trim() && visible.length === 0 && !loading && (
            <EmptyState
              message="No knowledge bases found"
              subMessage="Get started by creating your first knowledge base"
              onCreateClick={handleCreateClick}
              createButtonLabel="New Knowledge Base"
              showClearFilter={false}
            />
          )}

          {loading && visible.length > 0 && (
            <div className={styles.loadingMore}>
              Loading more knowledge bases...
            </div>
          )}
        </div>

        {/* Create Form Modal */}
        {showCreateForm && (
          <KnowledgeBaseForm
            mode="create"
            onClose={handleFormClose}
            onSave={handleFormSave}
          />
        )}

        {/* Update Form Modal */}
        {showUpdateForm && editKbData && (
          <KnowledgeBaseForm
            mode="update"
            kbData={editKbData}
            onClose={handleUpdateFormClose}
            onSave={handleUpdateFormSave}
          />
        )}
      </div>
    </>
  );
}
