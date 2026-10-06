import React, { useRef, useState } from "react";
import SubHeader from "../commonComponents/SubHeader";
import PageLayout from "../../iafComponents/GlobalComponents/PageLayout";
import TokenUsageTracking from "./TokenUsageTracking";

const TokenUsagePage = () => {
  const tokenDownloadClickRef = useRef(null);
  const [tokenReportDownloading, setTokenReportDownloading] = useState(false);

  return (
    <div className="pageContainer">
      <SubHeader
        heading="Token Usage"
        activeTab="token-usage"
        breadcrumbItems={null}
        showSearch={false}
        showPlusButton={false}
        showRefreshButton={false}
        quaternaryButtonLabel="Download Report"
        onQuaternaryButtonClick={() => tokenDownloadClickRef.current?.()}
        quaternaryButtonDisabled={tokenReportDownloading}
        quaternaryButtonIcon="download"
      />
      <PageLayout>
        <TokenUsageTracking
          onDownloadClickRef={tokenDownloadClickRef}
          onDownloadingChange={setTokenReportDownloading}
        />
      </PageLayout>
    </div>
  );
};

export default TokenUsagePage;
