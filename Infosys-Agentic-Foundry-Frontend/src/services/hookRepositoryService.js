import { APIs } from "../constant";
import useFetch from "../Hooks/useAxios";

/**
 * Hook Repository Service
 *
 * Wraps the /agentos/hooks CRUD + test endpoints.
 * Follows the same service-hook pattern as knowledgeBaseService.js.
 */
export const useHookRepositoryService = () => {
  const { fetchData, postData, putData, deleteData } = useFetch();

  /**
   * Normalize a raw hook object from the API into a consistent shape.
   */
  const mapHook = (hook) => ({
    hook_id: hook.hook_id || "",
    name: hook.name || "",
    filename: hook.filename || "",
    department: hook.department || "",
    description: hook.description || "",
    version: hook.version ?? 1,
    created_at: hook.created_at || "",
    updated_at: hook.updated_at || "",
    created_by: hook.created_by || "",
    // Only present on GET /hooks/{id}
    code: hook.code ?? undefined,
  });

  /**
   * List all hooks in the authenticated user's department.
   * GET /agentos/hooks  (department auto-resolved from JWT)
   */
  const listHooks = async () => {
    const response = await fetchData(APIs.HOOKS_BASE);
    const hooks = response?.hooks || response?.data?.hooks || (Array.isArray(response) ? response : []);
    return hooks.map(mapHook);
  };

  /**
   * Get a single hook's full details including source code.
   * GET /agentos/hooks/{hookId}
   */
  const getHookById = async (hookId) => {
    const response = await fetchData(`${APIs.HOOKS_BASE}/${encodeURIComponent(hookId)}`);
    const raw = response?.hook || response?.data?.hook || response;
    const code = response?.code ?? raw?.code ?? "";
    return { ...mapHook(raw), code };
  };

  /**
   * Create a new hook script.
   * POST /agentos/hooks  (body: name, code, description — department auto-resolved from JWT)
   */
  const createHook = async (payload) => {
    const response = await postData(APIs.HOOKS_BASE, payload);
    return response;
  };

  /**
   * Update an existing hook.
   * PUT /agentos/hooks/{hookId}  (body: name?, code?, description?)
   */
  const updateHook = async (hookId, payload) => {
    // List 2: PUT /{hook_id}  →  POST /update/{hook_id}
    const response = await putData(
      `${APIs.HOOKS_BASE}/update/${encodeURIComponent(hookId)}`,
      payload
    );
    return response;
  };

  /**
   * Delete a hook.
   * DELETE /agentos/hooks/{hookId}
   */
  const deleteHook = async (hookId) => {
    // List 2: DELETE /{hook_id}  →  POST /delete/{hook_id}
    const response = await deleteData(
      `${APIs.HOOKS_BASE}/delete/${encodeURIComponent(hookId)}`
    );
    return response;
  };

  /**
   * Dry-run test a hook script with sample data.
   * POST /agentos/hooks/{hookId}/test
   */
  const testHook = async (hookId, testPayload) => {
    // testPayload: { tool_name, tool_input, event }
    const response = await postData(
      `${APIs.HOOKS_BASE}/${encodeURIComponent(hookId)}/test`,
      testPayload
    );
    return response;
  };

  /**
   * Fetch built-in sample hook templates.
   * GET /agentos/hooks/sample-hooks
   */
  const getSampleHooks = async () => {
    const response = await fetchData(APIs.HOOKS_SAMPLE);
    const samples = response?.sample_hooks || response?.data?.sample_hooks || {};
    // Convert object map to array for easier iteration
    return Object.values(samples).map((hook) => ({
      name: hook.name || "",
      event: hook.event || "",
      description: hook.description || "",
      code: hook.code || "",
    }));
  };

  return {
    listHooks,
    getHookById,
    createHook,
    updateHook,
    deleteHook,
    testHook,
    getSampleHooks,
  };
};
