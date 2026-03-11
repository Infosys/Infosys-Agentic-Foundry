/**
 * FullModal - Centralized modal component for Agentic Pro UI
 *
 * This module exports the FullModal component and useModal hook,
 * providing a standardized modal experience across the application.
 *
 * @example
 * import { FullModal, useModal } from "../../iafComponents/GlobalComponents/FullModal";
 *
 * const MyComponent = () => {
 *   const { isOpen, open, close, data } = useModal();
 *
 *   return (
 *     <>
 *       <button onClick={() => open({ id: 1 })}>Open</button>
 *       <FullModal
 *         isOpen={isOpen}
 *         onClose={close}
 *         title="My Modal"
 *         headerInfo={[{ label: "ID", value: data?.id }]}
 *         footer={<Button onClick={close}>Close</Button>}
 *       >
 *         <p>Modal content for ID: {data?.id}</p>
 *       </FullModal>
 *     </>
 *   );
 * };
 */

export { default as FullModal } from "./FullModal";
export { default as useModal } from "./useModal";

// Default export for simpler imports
export { default } from "./FullModal";
