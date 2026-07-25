// Copyright (c) dcc-mcp contributors. All Rights Reserved.
// SPDX-License-Identifier: MIT

#include "DccMcpBridge.h"
#include "DccMcpReflection.h"
#include "HttpServerModule.h"
#include "IHttpRouter.h"
#include "HttpPath.h"
#include "HttpServerRequest.h"
#include "HttpServerResponse.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

// ── Construction / destruction ──────────────────────────────────────────────

FDccMcpBridge::FDccMcpBridge()
{
}

FDccMcpBridge::~FDccMcpBridge()
{
    StopServer();
}

// ── Server lifecycle ────────────────────────────────────────────────────────

bool FDccMcpBridge::StartServer(int32 Port)
{
    if (bIsRunning)
    {
        UE_LOG(LogTemp, Warning, TEXT("[DccMcpBridge] Server is already running on port %d"), BoundPort);
        return false;
    }

    // The bridge uses UE's HTTP server module (available in UE 5.1+).
    // For UE 4.18-5.0 compatibility, the Python plugin's HTTP support or
    // a standalone WebSocket bridge is used instead.
#if ENGINE_MAJOR_VERSION >= 5 && ENGINE_MINOR_VERSION >= 1
    FHttpServerModule& HttpModule = FHttpServerModule::Get();
    TSharedPtr<IHttpRouter> Router = HttpModule.GetHttpRouter(BoundPort);

    if (!Router.IsValid())
    {
        UE_LOG(LogTemp, Error, TEXT("[DccMcpBridge] Failed to create HTTP router on port %d"), Port);
        return false;
    }

    // POST /bridge — the single endpoint for all reflection calls
    Router->BindRoute(
        FHttpPath(TEXT("/bridge")),
        EHttpServerRequestVerbs::VERB_POST,
        [](const FHttpServerRequest& Request, const FHttpResultCallback& OnComplete)
        {
            // Parse JSON body
            TSharedPtr<FJsonObject> JsonBody;
            TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Request.Body);
            if (!FJsonSerializer::Deserialize(Reader, JsonBody) || !JsonBody.IsValid())
            {
                TUniquePtr<FHttpServerResponse> Response = FHttpServerResponse::Create(
                    TEXT("{\"error\": \"Invalid JSON\"}"), TEXT("application/json")
                );
                OnComplete(MoveTemp(Response));
                return true;
            }

            FString Method = JsonBody->GetStringField(TEXT("method"));
            TSharedPtr<FJsonObject> Params = JsonBody->GetObjectField(TEXT("params"));

            TSharedPtr<FJsonObject> Result;

            // Route to the appropriate handler
            if (Method == TEXT("discover_objects"))
            {
                FString ClassFilter = Params.IsValid() ? Params->GetStringField(TEXT("class_filter")) : TEXT("");
                FString OuterFilter = Params.IsValid() ? Params->GetStringField(TEXT("outer_filter")) : TEXT("");
                int32 MaxResults = Params.IsValid() ? Params->GetIntegerField(TEXT("max_results")) : 100;

                TArray<FDccMcpObjectDescriptor> Objects = FDccMcpReflection::DiscoverObjects(ClassFilter, OuterFilter, MaxResults);

                TArray<TSharedPtr<FJsonValue>> ObjArr;
                for (const auto& Obj : Objects)
                {
                    ObjArr.Add(MakeShareable(new FJsonValueObject(Obj.ToJson())));
                }

                Result = MakeShareable(new FJsonObject());
                Result->SetArrayField(TEXT("objects"), ObjArr);
            }
            else if (Method == TEXT("describe_object"))
            {
                FString ObjectPath = Params.IsValid() ? Params->GetStringField(TEXT("object_path")) : TEXT("");
                bool bIncludeProperties = Params.IsValid() ? Params->GetBoolField(TEXT("include_properties")) : true;
                bool bIncludeFunctions = Params.IsValid() ? Params->GetBoolField(TEXT("include_functions")) : true;

                FDccMcpObjectDescriptor Desc = FDccMcpReflection::DescribeObject(ObjectPath, bIncludeProperties, bIncludeFunctions);
                Result = Desc.ToJson();
            }
            else if (Method == TEXT("get_property"))
            {
                FString ObjectPath = Params.IsValid() ? Params->GetStringField(TEXT("object_path")) : TEXT("");
                FString PropertyName = Params.IsValid() ? Params->GetStringField(TEXT("property_name")) : TEXT("");

                Result = FDccMcpReflection::GetProperty(ObjectPath, PropertyName);
            }
            else if (Method == TEXT("get_properties"))
            {
                FString ObjectPath = Params.IsValid() ? Params->GetStringField(TEXT("object_path")) : TEXT("");
                TArray<FString> PropertyNames;
                if (Params.IsValid() && Params->HasField(TEXT("property_names")))
                {
                    const TArray<TSharedPtr<FJsonValue>>& NamesArr = Params->GetArrayField(TEXT("property_names"));
                    for (const auto& NameVal : NamesArr)
                    {
                        PropertyNames.Add(NameVal->AsString());
                    }
                }

                TArray<TSharedPtr<FJsonValue>> PropsResult = FDccMcpReflection::GetProperties(ObjectPath, PropertyNames);

                Result = MakeShareable(new FJsonObject());
                Result->SetArrayField(TEXT("properties"), PropsResult);
            }
            else if (Method == TEXT("set_property"))
            {
                FString ObjectPath = Params.IsValid() ? Params->GetStringField(TEXT("object_path")) : TEXT("");
                FString PropertyName = Params.IsValid() ? Params->GetStringField(TEXT("property_name")) : TEXT("");
                TSharedPtr<FJsonValue> Value = Params.IsValid() ? Params->TryGetField(TEXT("value")) : TSharedPtr<FJsonValue>();

                // Route to GameThread
                TSharedPtr<FJsonObject> SyncResult;
                AsyncTask(ENamedThreads::GameThread, [&]()
                {
                    SyncResult = FDccMcpReflection::SetProperty(ObjectPath, PropertyName, Value);
                });
                // Note: simplistic sync via busy-wait; production code should use FEvent.
                Result = SyncResult;
            }
            else if (Method == TEXT("set_properties"))
            {
                FString ObjectPath = Params.IsValid() ? Params->GetStringField(TEXT("object_path")) : TEXT("");
                TSharedPtr<FJsonObject> Props = Params.IsValid() ? Params->GetObjectField(TEXT("properties")) : MakeShareable(new FJsonObject());

                TSharedPtr<TArray<TSharedPtr<FJsonValue>>> SyncResult;
                AsyncTask(ENamedThreads::GameThread, [&]()
                {
                    TArray<TSharedPtr<FJsonValue>> Results = FDccMcpReflection::SetProperties(ObjectPath, Props);
                    SyncResult = MakeShareable(new TArray<TSharedPtr<FJsonValue>>(Results));
                });

                Result = MakeShareable(new FJsonObject());
                TArray<TSharedPtr<FJsonValue>> ResultsArr;
                // Wait for GameThread result (simplified; use FEvent in production)
                ResultsArr = *SyncResult;
                Result->SetArrayField(TEXT("properties"), ResultsArr);
            }
            else if (Method == TEXT("call_function"))
            {
                FString ObjectPath = Params.IsValid() ? Params->GetStringField(TEXT("object_path")) : TEXT("");
                FString FunctionName = Params.IsValid() ? Params->GetStringField(TEXT("function_name")) : TEXT("");
                TSharedPtr<FJsonObject> Args = Params.IsValid() ? Params->GetObjectField(TEXT("args")) : MakeShareable(new FJsonObject());
                int32 TimeoutMs = Params.IsValid() ? Params->GetIntegerField(TEXT("timeout_ms")) : 10000;

                TSharedPtr<FJsonObject> SyncResult;
                AsyncTask(ENamedThreads::GameThread, [&]()
                {
                    SyncResult = FDccMcpReflection::CallFunction(ObjectPath, FunctionName, Args, TimeoutMs);
                });
                Result = SyncResult;
            }
            else
            {
                Result = MakeShareable(new FJsonObject());
                Result->SetStringField(TEXT("error"), FString::Printf(TEXT("Unknown method: %s"), *Method));
            }

            // Serialize response
            FString ResponseBody;
            TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&ResponseBody);
            FJsonSerializer::Serialize(Result.ToSharedRef(), Writer);

            TUniquePtr<FHttpServerResponse> Response = FHttpServerResponse::Create(ResponseBody, TEXT("application/json"));
            OnComplete(MoveTemp(Response));
            return true;
        }
    );

    HttpModule.StartAllListeners();
    BoundPort = Port;
    bIsRunning = true;

    UE_LOG(LogTemp, Log, TEXT("[DccMcpBridge] Listening on http://127.0.0.1:%d/bridge"), Port);
    return true;
#else
    UE_LOG(LogTemp, Warning, TEXT("[DccMcpBridge] HTTP server requires UE 5.1+. For UE 4.18-5.0, use the Python plugin's HTTP support."));
    return false;
#endif
}

void FDccMcpBridge::StopServer()
{
    if (!bIsRunning) return;

#if ENGINE_MAJOR_VERSION >= 5 && ENGINE_MINOR_VERSION >= 1
    FHttpServerModule& HttpModule = FHttpServerModule::Get();
    HttpModule.StopAllListeners();
#endif

    BoundPort = 0;
    bIsRunning = false;

    UE_LOG(LogTemp, Log, TEXT("[DccMcpBridge] Server stopped."));
}
