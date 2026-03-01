// @ts-check

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: "Scholarr",
  tagline: "Self-hosted academic publication tracker",
  favicon: "img/favicon.ico",

  url: "https://justinzeus.github.io",
  baseUrl: "/scholarr/",

  organizationName: "JustinZeus",
  projectName: "scholarr",

  onBrokenLinks: "throw",
  onBrokenMarkdownLinks: "warn",

  i18n: {
    defaultLocale: "en",
    locales: ["en"],
  },

  presets: [
    [
      "classic",
      /** @type {import('@docusaurus/preset-classic').Options} */
      ({
        docs: {
          path: "..",
          routeBasePath: "/",
          sidebarPath: require.resolve("./sidebars.js"),
          exclude: ["website/**", "README.md"],
        },
        blog: false,
        theme: {
          customCss: require.resolve("./src/css/custom.css"),
        },
      }),
    ],
  ],

  themeConfig:
    /** @type {import('@docusaurus/preset-classic').ThemeConfig} */
    ({
      navbar: {
        title: "Scholarr",
        items: [
          { to: "/user/overview", label: "User Guide", position: "left" },
          {
            to: "/developer/overview",
            label: "Developer",
            position: "left",
          },
          {
            to: "/operations/overview",
            label: "Operations",
            position: "left",
          },
          { to: "/reference/overview", label: "Reference", position: "left" },
          {
            href: "https://github.com/JustinZeus/scholarr",
            label: "GitHub",
            position: "right",
          },
        ],
      },
      footer: {
        style: "dark",
        copyright: `Copyright \u00a9 ${new Date().getFullYear()} Scholarr. Built with Docusaurus.`,
      },
    }),
};

module.exports = config;
