// Copyright (c) dcc-mcp contributors. All Rights Reserved.
// SPDX-License-Identifier: MIT

#include "DccMcpUnrealModule.h"
#include "DccMcpBridge.h"
#include "DccMcpSecurity.h"

#include "Modules/ModuleManager.h"
#include "Misc/CommandLine.h"
#include "HAL/PlatformMisc.h"

#if WITH_EDITOR
#include "Editor.h"
#include "Framework/Application/SlateApplication.h"
#endif

#define LOCTEXT_NAMESPACE "FDccMcpUnrealModule"

static TUniquePtr<FDccMcpBridge> BridgeInstance;

void FDccMcpUnrealModule::StartupModule()
{
    UE_LOG(LogTemp, Log, TEXT("[DccMcpUnreal] Module starting..."));

    FDccMcpSecurity::bAllowPropertyWrite =
        FPlatformMisc::GetEnvironmentVariable(TEXT("DCC_MCP_UNREAL_ALLOW_WRITE")) == TEXT("1");
    FDccMcpSecurity::bAllowFunctionCall =
        FPlatformMisc::GetEnvironmentVariable(TEXT("DCC_MCP_UNREAL_ALLOW_EXECUTE")) == TEXT("1");

    // If the plugin was loaded via -dccmcpbridge=PORT on the command line,
    // auto-start the bridge server immediately.
    int32 AutoPort = 0;
    if (FParse::Value(FCommandLine::Get(), TEXT("-dccmcpbridge="), AutoPort) && AutoPort > 0)
    {
        BridgeInstance = MakeUnique<FDccMcpBridge>();
        if (BridgeInstance->StartServer(AutoPort))
        {
            UE_LOG(LogTemp, Log, TEXT("[DccMcpUnreal] Bridge started on port %d"), AutoPort);
        }
        else
        {
            UE_LOG(LogTemp, Error, TEXT("[DccMcpUnreal] Bridge failed to start on port %d"), AutoPort);
        }
    }

    RegisterConsoleCommands();
    bModuleStarted = true;

    UE_LOG(LogTemp, Log, TEXT("[DccMcpUnreal] Module started (security: write=%s, execute=%s, main_thread=%s)"),
        FDccMcpSecurity::bAllowPropertyWrite ? TEXT("ON") : TEXT("OFF"),
        FDccMcpSecurity::bAllowFunctionCall ? TEXT("ON") : TEXT("OFF"),
        FDccMcpSecurity::bEnforceGameThread ? TEXT("ON") : TEXT("OFF"));
}

void FDccMcpUnrealModule::ShutdownModule()
{
    UnregisterConsoleCommands();

    if (BridgeInstance.IsValid())
    {
        BridgeInstance->StopServer();
        BridgeInstance.Reset();
    }

    bModuleStarted = false;

    UE_LOG(LogTemp, Log, TEXT("[DccMcpUnreal] Module shut down."));
}

bool FDccMcpUnrealModule::IsBridgeActive()
{
    return BridgeInstance.IsValid() && BridgeInstance->IsRunning();
}

void FDccMcpUnrealModule::RegisterConsoleCommands()
{
    // Console commands for diagnostics:
    //   DccMcp.Status   — print bridge status
    //   DccMcp.Start    — start bridge on a port
    //   DccMcp.Stop     — stop the bridge

    IConsoleManager::Get().RegisterConsoleCommand(
        TEXT("DccMcp.Status"),
        TEXT("Print the DCC MCP bridge status"),
        FConsoleCommandDelegate::CreateLambda([]()
        {
            if (BridgeInstance.IsValid() && BridgeInstance->IsRunning())
            {
                UE_LOG(LogTemp, Log, TEXT("[DccMcp] Bridge running on port %d"), BridgeInstance->GetPort());
                UE_LOG(LogTemp, Log, TEXT("[DccMcp] Security: write=%s execute=%s game_thread=%s"),
                    FDccMcpSecurity::bAllowPropertyWrite ? TEXT("ON") : TEXT("OFF"),
                    FDccMcpSecurity::bAllowFunctionCall ? TEXT("ON") : TEXT("OFF"),
                    FDccMcpSecurity::bEnforceGameThread ? TEXT("ON") : TEXT("OFF"));
            }
            else
            {
                UE_LOG(LogTemp, Log, TEXT("[DccMcp] Bridge is NOT running"));
            }
        })
    );

    IConsoleManager::Get().RegisterConsoleCommand(
        TEXT("DccMcp.Start"),
        TEXT("Start the DCC MCP bridge on a port (DccMcp.Start <port>)"),
        FConsoleCommandWithArgsDelegate::CreateLambda([](const TArray<FString>& Args)
        {
            if (Args.Num() < 1)
            {
                UE_LOG(LogTemp, Warning, TEXT("Usage: DccMcp.Start <port>"));
                return;
            }
            int32 Port = FCString::Atoi(*Args[0]);
            if (Port <= 0 || Port > 65535)
            {
                UE_LOG(LogTemp, Warning, TEXT("Invalid port: %d"), Port);
                return;
            }
            BridgeInstance = MakeUnique<FDccMcpBridge>();
            if (BridgeInstance->StartServer(Port))
            {
                UE_LOG(LogTemp, Log, TEXT("[DccMcp] Bridge started on port %d"), Port);
            }
        })
    );

    IConsoleManager::Get().RegisterConsoleCommand(
        TEXT("DccMcp.Stop"),
        TEXT("Stop the DCC MCP bridge"),
        FConsoleCommandDelegate::CreateLambda([]()
        {
            if (BridgeInstance.IsValid())
            {
                BridgeInstance->StopServer();
                BridgeInstance.Reset();
                UE_LOG(LogTemp, Log, TEXT("[DccMcp] Bridge stopped"));
            }
        })
    );
}

void FDccMcpUnrealModule::UnregisterConsoleCommands()
{
    if (IConsoleManager::Get().IsNameRegistered(TEXT("DccMcp.Status")))
    {
        IConsoleManager::Get().UnregisterConsoleObject(TEXT("DccMcp.Status"));
    }
    if (IConsoleManager::Get().IsNameRegistered(TEXT("DccMcp.Start")))
    {
        IConsoleManager::Get().UnregisterConsoleObject(TEXT("DccMcp.Start"));
    }
    if (IConsoleManager::Get().IsNameRegistered(TEXT("DccMcp.Stop")))
    {
        IConsoleManager::Get().UnregisterConsoleObject(TEXT("DccMcp.Stop"));
    }
}

#undef LOCTEXT_NAMESPACE

IMPLEMENT_MODULE(FDccMcpUnrealModule, DccMcpUnreal)
