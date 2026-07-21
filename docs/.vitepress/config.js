import { defineConfig } from 'vitepress'

export default defineConfig({
  title: 'dcc-mcp-unreal',
  description: 'MCP server for Unreal Engine integration',
  base: '/dcc-mcp-unreal/',
  themeConfig: {
    nav: [
      { text: 'Home', link: '/' },
      { text: 'Install', link: '/installation' },
    ],
    sidebar: [
      { text: 'Overview', link: '/' },
      { text: 'Installation Guide', link: '/installation' },
      { text: 'UE Version Compatibility', link: '/unreal-version-compatibility' },
      { text: 'MSVC-Kit Guide', link: '/msvc-kit-guide' },
    ],
  },
})
