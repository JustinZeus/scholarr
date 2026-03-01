/** @type {import('@docusaurus/plugin-content-docs').SidebarsConfig} */
const sidebars = {
  docs: [
    "index",
    {
      type: "category",
      label: "User Guide",
      items: [
        "user/overview",
        "user/getting-started",
        "user/configuration",
      ],
    },
    {
      type: "category",
      label: "Developer",
      items: [
        "developer/overview",
        "developer/architecture",
        "developer/local-development",
        "developer/contributing",
        "developer/ingestion",
        "developer/frontend-theme-inventory",
        "developer/testing",
      ],
    },
    {
      type: "category",
      label: "Operations",
      items: [
        "operations/overview",
        "operations/deployment",
        "operations/database-runbook",
        "operations/scrape-safety-runbook",
        "operations/arxiv-runbook",
      ],
    },
    {
      type: "category",
      label: "Reference",
      items: [
        "reference/overview",
        "reference/api",
        "reference/environment",
        "reference/changelog",
      ],
    },
  ],
};

module.exports = sidebars;
