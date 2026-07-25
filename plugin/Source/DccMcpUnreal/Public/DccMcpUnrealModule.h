// Copyright (c) dcc-mcp contributors. All Rights Reserved.
// SPDX-License-Identifier: MIT

#pragma once

#include "CoreMinimal.h"
#include "Modules/ModuleManager.h"

/**
 * DCC MCP Unreal Editor Module
 *
 * Provides the secure UObject reflection bridge between the dcc-mcp-core
 * Python adapter and Unreal Engine's native reflection system.
 *
 * Design constraints:
 * - Fail-closed: all access denied unless explicitly allowlisted.
 * - Main-thread: all UObject mutations execute on GameThread.
 * - UE 4.18+: conditional compilation for API differences.
 * - UE 5.x: full support with enhanced reflection APIs.
 */
class FDccMcpUnrealModule : public IModuleInterface
{
public:
    /** IModuleInterface implementation */
    virtual void StartupModule() override;
    virtual void ShutdownModule() override;

    /** @return true if the module is loaded and the bridge is active. */
    static bool IsBridgeActive();

private:
    /** Register console commands for diagnostics. */
    void RegisterConsoleCommands();

    /** Unregister console commands. */
    void UnregisterConsoleCommands();

    /** Handle for the tick delegate (Slate pre-tick or FTicker). */
    FDelegateHandle TickDelegateHandle;

    /** True once StartupModule completes. */
    bool bModuleStarted = false;
};
