/** @type {import('@docusaurus/plugin-content-docs').SidebarsConfig} */
const sidebars = {
  docsSidebar: [
    "index",
    {
      type: "category",
      label: "Users",
      items: ["user/overview", "user/getting-started"],
    },
    {
      type: "category",
      label: "Operations",
      items: [
        "operations/overview",
        "operations/scrape-safety-runbook",
        "operations/database-runbook",
        "operations/migration-checklist",
      ],
    },
    {
      type: "category",
      label: "Developers",
      items: [
        "developer/overview",
        "developer/documentation-standards",
        "developer/local-development",
        "developer/architecture",
        "developer/contributing",
        "developer/frontend-theme-inventory",
      ],
    },
    {
      type: "category",
      label: "Reference",
      items: ["reference/overview", "reference/api-contract", "reference/environment"],
    },
  ],
};

module.exports = sidebars;
