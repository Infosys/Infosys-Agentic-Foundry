import React, { useState } from "react";
import ThreeColumnLayout, { SplitLayout } from "../commonComponents/ThreeColumnLayout";
import EvaluationScore from "../AdminScreen/EvaluationScore";
import AgentsEvaluator from "../AgentsEvaluator";
import GroundTruth from "../GroundTruth/GroundTruth";
import ConsistencyTab from "./ConsistencyTab";
import styles from "./EvaluationPage.module.css";

/**
 * EvaluationPageNew - Rebuilt using ThreeColumnLayout parent component
 * This demonstrates how to use the reusable 3-column layout with configuration
 */

const EvaluationPageNew = () => {
  const [activeMetricsSubTab, setActiveMetricsSubTab] = useState("evaluationRecords");
  const [consistencyResponse, setConsistencyResponse] = useState(null);
  const [llmJudgeResponse, setLlmJudgeResponse] = useState(null);

  // Handler to pass to ConsistencyTab for response
  const handleConsistencyResponse = (response) => {
    setConsistencyResponse(response);
  };

  // Handler to pass to AgentsEvaluator for response
  const handleLlmJudgeResponse = (response) => {
    setLlmJudgeResponse(response);
  };

  // Navigation configuration for the left sidebar (single object, static keys, no separators)
  const navigationConfig = [
    {
      type: "section",
      key: "llmJudge",
      label: "LLM as Judge",
      splitLayout: true,
      renderSplitLayout: (Component, componentProps) => (
        <SplitLayout
          FormComponent={Component}
          formProps={{ onResponse: handleLlmJudgeResponse, ...componentProps }}
          response={llmJudgeResponse}
          responseTitle="Evaluation Result"
          parseJson={true}
        />
      ),
      component: AgentsEvaluator
    },
  // separator removed
    {
      type: "section",
      key: "metrics",
      label: "Metrics",
      children: [
        {
          type: "item",
          key: "evaluationRecords",
          label: "Evaluation Records",
          component: EvaluationScore,
          componentProps: { activeMetricsSubTab: "evaluationRecords" }
        },
        {
          type: "item",
          key: "toolsEfficiency",
          label: "Tools Efficiency",
          component: EvaluationScore,
          componentProps: { activeMetricsSubTab: "toolsEfficiency" }
        },
        {
          type: "item",
          key: "agentsEfficiency",
          label: "Agents Efficiency",
          component: EvaluationScore,
          componentProps: { activeMetricsSubTab: "agentsEfficiency" }
        }
      ]
    },
  // separator removed
    {
      type: "section",
      key: "evaluation",
      label: "Evaluation",
      children: [
        {
          type: "item",
          key: "groundtruth",
          label: "Ground Truth",
          component: GroundTruth
        },
        {
          type: "item",
          key: "consistency",
          label: "Consistency",
          splitLayout: true,
          renderSplitLayout: (Component, componentProps) => (
            <SplitLayout
              FormComponent={Component}
              formProps={{ onResponse: handleConsistencyResponse, ...componentProps }}
              response={consistencyResponse}
              responseTitle="Response"
              parseJson={false}
            />
          ),
          component: ConsistencyTab
        }
      ]
    }
  ];

  return (
    <ThreeColumnLayout
      navigationConfig={navigationConfig}
      defaultActiveTab="llmJudge"
    />
  );
};

export default EvaluationPageNew;
