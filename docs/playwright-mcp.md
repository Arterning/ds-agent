
## stdio 方式启动MCP

本地模式

```json
"playwright": {
      "command": "npx",
      "args": [
        "@playwright/mcp@latest"
      ]
  }
```

也可以Docker方式

```json
{
  "mcpServers": {
    "playwright": {
        "command": "docker",
        "args": [
          "run",
          "-i",
          "--rm",
          "--init",
          "--pull=always",
          "mcr.microsoft.com/playwright/mcp"
        ]
      }
  }
}

```


## http方式连接MCP服务器

Docker 启动 MCP 服务器

```yaml
playwright:
  image: mcr.microsoft.com/playwright/mcp
  container_name: fba_playwright
  restart: unless-stopped
  profiles:
    - playwright
  networks:
    - fba_network
  ports:
    - 3001:3000
  command:
    - "--port"
    - "3000"
    - "--host"
    - "0.0.0.0"
    - "--allowed-hosts"
    - "*"
```


```json
{
  "mcpServers": {
    "playwright": {
      "url": "http://remoteip:3001/mcp"
    }
  }
}

```