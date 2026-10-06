import Loader from "./Loader";

const MsalAuthLoader = () => (
  <div style={{ position: "fixed", inset: 0, zIndex: 9999 }}>
    <Loader />
  </div>
);

export default MsalAuthLoader;
