# chongdashu/unreal-mcp 架构分析与 dcc-mcp-unreal 可复用经验

## 1. 总体架构对比

| 维度 | unreal-mcp (chongdashu) | dcc-mcp-unreal (本仓库) |
|------|------------------------|------------------------|
| **传输层** | 原生 TCP socket (端口 55557) | Streamable HTTP MCP (动态端口 + 网关 9765) |
| **Python 端** | 独立 FastMCP 进程 (stdio transport) | 嵌入 Unreal 进程内 (in-process) |
| **C++ 端** | Editor Subsystem + 独立线程 TCP 服务器 | 最小插件 (仅 Automation Library) |
| **命令分发** | 字符串路由 (if-else 链) | 结构化 Skill 系统 (SKILL.md + tools.yaml) |
| **工具热加载** | 显式 import 注册 | 文件系统扫描 + 自动发现 |
| **多客户端** | JSON 配置文件 (不同路径) | 网关选举 + 故障转移 |
| **Blueprint 节点** | 完整实现 (事件/函数/变量/连线) | 未实现 (roadmap v0.2.0) |

## 2. TCP Bridge vs HTTP 稳定性取舍

### unreal-mcp 的 TCP 方案

```python
# Python 端: 每次命令都新建连接 (Unreal 会关闭连接)
def send_command(self, command, params):
    self.socket.close()  # 先关闭旧连接
    self.connect()       # 重新连接
    self.socket.sendall(command_json.encode('utf-8'))
    response = self.receive_full_response(self.socket)
    self.socket.close()  # 命令完成后关闭
```

**关键发现**:
- **每次命令都重新建立 TCP 连接** — 因为 Unreal 的 C++ TCP 服务器在收到数据后立即关闭连接
- `TCP_NODELAY` + `SO_KEEPALIVE` 用于低延迟和连接检测
- 64KB 缓冲区 (发送和接收)
- `receive_full_response()` 通过 JSON 解析完整性判断是否接收完毕
- 5 秒超时设置

**C++ 端特点**:
```cpp
// MCPServerRunnable::Run() - 独立线程运行
// 非阻塞 socket + HasPendingConnection 轮询
// SE_EWOULDBLOCK 和 SE_EINTR 容错处理
// 100ms 轮询间隔 (FPlatformProcess::Sleep(0.1f))
```

**稳定性问题**:
1. 每次命令都重新握手 — 增加延迟
2. 单连接单命令模型 — 无法并发
3. 线程安全问题 — GameThread 通过 Promise/Future 通信
4. 轮询模型 — 空闲时浪费 CPU

### dcc-mcp-unreal 的 HTTP 方案优势

- **持久连接**: HTTP keep-alive，无需重复握手
- **并发友好**: 多客户端可同时连接
- **成熟协议**: HTTP 语义明确 (状态码、头部、会话)
- **网关层**: 支持健康检查、故障转移、选举
- **线程安全**: 通过 Slate tick 回调将操作序列化到主线程

**建议**: dcc-mcp-unreal 的 HTTP 方案已经优于 unreal-mcp 的 TCP 方案。**不需要引入 TCP bridge**。但可以从 unreal-mcp 学习:

1. **连接状态监控**: unreal-mcp 的 `receive_full_response` 分块接收模式可改进 HTTP 长轮询场景
2. **错误恢复**: 每次命令重连策略适合不可靠网络环境
3. **低延迟优化**: `TCP_NODELAY` 对应 HTTP 的 `Connection: keep-alive`

## 3. 工具模块热加载

### unreal-mcp 方案 (简单显式)

```python
# 显式 import + register 模式
from tools.editor_tools import register_editor_tools
from tools.blueprint_tools import register_blueprint_tools
from tools.node_tools import register_blueprint_node_tools
from tools.project_tools import register_project_tools
from tools.umg_tools import register_umg_tools

register_editor_tools(mcp)
register_blueprint_tools(mcp)
# ...
```

每个工具模块提供 `register_*_tools(mcp: FastMCP)` 函数，内部用 `@mcp.tool()` 装饰器注册。

**优点**: 简单直接，类型安全
**缺点**: 添加新模块需要修改主文件

### dcc-mcp-unreal 方案 (声明式扫描)

```yaml
# tools.yaml - 声明式工具定义
tools:
  - name: list_actors
    source_file: scripts/list_actors.py
    execution: sync
    affinity: main
    input_schema: ...
```

```python
# 自动发现 + 加载
server.register_builtin_actions(extra_skill_paths=...)
server._load_discovered_unreal_skills()
```

**优点**: 完全解耦，新技能只需添加目录
**缺点**: 启动时需扫描文件系统

**建议**: dcc-mcp-unreal 的声明式方案更优。**无需改变**。

## 4. Blueprint 节点图编辑抽象

### unreal-mcp 的实现 (可复用模式)

unreal-mcp 通过 `BlueprintNodeCommands` 实现了完整的节点图编辑:

```cpp
// C++ 端: 命令处理器
class FUnrealMCPBlueprintNodeCommands {
    TSharedPtr<FJsonObject> HandleCommand(const FString& CommandType, 
                                           const TSharedPtr<FJsonObject>& Params);
    // 支持: add_blueprint_event_node, add_blueprint_function_node,
    //       connect_blueprint_nodes, add_blueprint_variable, etc.
};
```

```python
# Python 端: 工具注册 (node_tools.py)
@mcp.tool()
def add_blueprint_event_node(ctx, blueprint_name, event_name, node_position=None):
    unreal.send_command("add_blueprint_event_node", {...})

@mcp.tool()
def connect_blueprint_nodes(ctx, blueprint_name, source_node_id, source_pin, 
                             target_node_id, target_pin):
    unreal.send_command("connect_blueprint_nodes", {...})
```

**节点操作抽象层次**:
1. **事件节点**: `add_blueprint_event_node` → BeginPlay, Tick 等
2. **函数调用节点**: `add_blueprint_function_node` → target + function_name
3. **变量节点**: `add_blueprint_variable` → 类型系统
4. **连线**: `connect_blueprint_nodes` → source_pin → target_pin
5. **引用节点**: `add_blueprint_self_reference`, `add_blueprint_get_self_component_reference`
6. **查询**: `find_blueprint_nodes` → 按类型/事件过滤

**对 dcc-mcp-unreal 的建议**:

创建 `unreal-blueprints` 技能，提供以下工具:

```yaml
# skills/unreal-blueprints/tools.yaml
tools:
  - name: create_blueprint_class
    description: Create a new Blueprint class from a parent class
    source_file: scripts/create_blueprint_class.py
    execution: sync
    affinity: main

  - name: add_blueprint_event_node
    description: Add an event node (BeginPlay, Tick) to a Blueprint graph
    source_file: scripts/add_event_node.py
    execution: sync
    affinity: main

  - name: add_blueprint_function_node
    description: Add a function call node to a Blueprint graph
    source_file: scripts/add_function_node.py
    execution: sync
    affinity: main

  - name: connect_blueprint_nodes
    description: Connect two nodes in a Blueprint graph
    source_file: scripts/connect_nodes.py
    execution: sync
    affinity: main

  - name: add_blueprint_variable
    description: Add a variable to a Blueprint
    source_file: scripts/add_variable.py
    execution: sync
    affinity: main

  - name: compile_blueprint
    description: Compile a Blueprint
    source_file: scripts/compile_blueprint.py
    execution: sync
    affinity: main
```

关键 API 映射 (unreal-mcp C++ → dcc-mcp-unreal Python):

| unreal-mcp C++ API | Unreal Python API |
|-------------------|-------------------|
| `FKismetEditorUtilities::CreateBlueprint` | `unreal.BlueprintEditorLibrary` |
| `UK2Node_Event` 创建 | `unreal.K2Node_Event` |
| `UK2Node_CallFunction` 创建 | `unreal.K2Node_CallFunction` |
| `UEdGraphPin::MakeLinkTo` | `unreal.EdGraphPin.make_link_to()` |
| `FBlueprintEditorUtils::AddMemberVariable` | `unreal.BlueprintEditorLibrary.add_member_variable()` |
| `FKismetEditorUtilities::CompileBlueprint` | `unreal.BlueprintEditorLibrary.compile_blueprint()` |

## 5. 多客户端配置策略

### unreal-mcp 方案

```json
// 统一 JSON 格式，不同客户端不同路径
{
  "mcpServers": {
    "unrealMCP": {
      "command": "uv",
      "args": ["--directory", "<path>", "run", "unreal_mcp_server.py"]
    }
  }
}
```

| 客户端 | 配置文件路径 |
|--------|------------|
| Claude Desktop | `~/.config/claude-desktop/mcp.json` |
| Cursor | `.cursor/mcp.json` |
| Windsurf | `~/.config/windsurf/mcp.json` |

### dcc-mcp-unreal 方案

- **网关选举**: 自动故障转移，先到先得
- **动态端口**: OS 分配空闲端口，网关端口固定 9765
- **发现机制**: `dcc-mcp-cli list` + 环境变量 `DCC_MCP_IPC_ADDRESS`
- **会话管理**: Streamable HTTP 协议的 `Mcp-Session-Id`

**建议**: dcc-mcp-unreal 的网关选举方案更先进。unreal-mcp 的多客户端配置文档可以借鉴用于 dcc-mcp-unreal 的客户端配置指南。

## 6. 可立即实施的改进

### 优先级 1: Blueprint 节点图编辑技能 (unreal-blueprints)

这是 unreal-mcp 最有价值的部分，dcc-mcp-unreal 完全缺失。

### 优先级 2: 连接弹性改进

从 unreal-mcp 学习分块接收和错误恢复模式，增强 `UnrealMainThreadDispatcher` 的超时处理。

### 优先级 3: 预配置示例项目

unreal-mcp 的 `MCPGameProject` 降低了上手门槛。dcc-mcp-unreal 可提供类似的快速启动配置。

### 优先级 4: 诊断日志

unreal-mcp 的详细日志 (`unreal_mcp.log`) 包含文件:行号，适合调试。dcc-mcp-unreal 可增强日志格式。

## 7. 不推荐采纳的模式

1. **TCP 直连替代 HTTP**: dcc-mcp-unreal 的 HTTP 方案更成熟
2. **显式 import 注册**: 声明式扫描更适合技能生态
3. **每次命令重连**: 增加不必要的延迟
4. **字符串路由 (if-else 链)**: 命令处理器模式更清晰
5. **独立 Python 进程**: 进程内执行避免序列化开销
