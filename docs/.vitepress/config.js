import { defineConfig } from 'vitepress'

export default defineConfig({
  title: 'dcc-mcp-unreal',
  description: 'MCP server for Unreal Engine integration',
  base: '/dcc-mcp-unreal/',
  themeConfig: {
    nav: [{ text: 'Home', link: '/' }],
    sidebar: [{ text: 'Overview', link: '/' }],
  },
})
