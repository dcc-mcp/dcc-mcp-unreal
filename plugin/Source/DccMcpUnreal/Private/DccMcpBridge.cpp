// Copyright (c) dcc-mcp contributors. All Rights Reserved.
// SPDX-License-Identifier: MIT

#include "DccMcpBridge.h"

#if (ENGINE_MAJOR_VERSION > 5) || (ENGINE_MAJOR_VERSION == 5 && ENGINE_MINOR_VERSION >= 1)

#include "Async/Async.h"
#include "Containers/StringConv.h"
#include "DccMcpReflection.h"
#include "Dom/JsonObject.h"
#include "HttpPath.h"
#include "HttpRequestHandler.h"
#include "HttpServerModule.h"
#include "HttpServerRequest.h"
#include "HttpServerResponse.h"
#include "IHttpRouter.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

namespace
{
TSharedPtr<FJsonObject> MakeBridgeError(const FString& Message)
{
    TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
    Result->SetBoolField(TEXT("success"), false);
    Result->SetStringField(TEXT("error"), Message);
    return Result;
}

FString ReadString(const TSharedPtr<FJsonObject>& Object, const TCHAR* FieldName)
{
    FString Value;
    if (Object.IsValid())
    {
        Object->TryGetStringField(FieldName, Value);
    }
    return Value;
}

bool ReadBool(const TSharedPtr<FJsonObject>& Object, const TCHAR* FieldName, bool DefaultValue)
{
    bool Value = DefaultValue;
    if (Object.IsValid())
    {
        Object->TryGetBoolField(FieldName, Value);
    }
    return Value;
}

int32 ReadInteger(const TSharedPtr<FJsonObject>& Object, const TCHAR* FieldName, int32 DefaultValue)
{
    int32 Value = DefaultValue;
    if (Object.IsValid())
    {
        Object->TryGetNumberField(FieldName, Value);
    }
    return Value;
}

TSharedPtr<FJsonObject> ReadObject(const TSharedPtr<FJsonObject>& Object, const TCHAR* FieldName)
{
    const TSharedPtr<FJsonObject>* Value = nullptr;
    if (Object.IsValid() && Object->TryGetObjectField(FieldName, Value) && Value != nullptr)
    {
        return *Value;
    }
    return MakeShared<FJsonObject>();
}

TSharedPtr<FJsonObject> DispatchOnGameThread(
    const FString& Method,
    const TSharedPtr<FJsonObject>& Params)
{
    if (!IsInGameThread())
    {
        return MakeBridgeError(TEXT("Bridge dispatch must execute on the Game Thread"));
    }

    if (Method == TEXT("discover_objects"))
    {
        const FString ClassFilter = ReadString(Params, TEXT("class_filter"));
        const FString OuterFilter = ReadString(Params, TEXT("outer_filter"));
        const int32 MaxResults = FMath::Clamp(ReadInteger(Params, TEXT("max_results"), 100), 1, 1000);
        const TArray<FDccMcpObjectDescriptor> Objects =
            FDccMcpReflection::DiscoverObjects(ClassFilter, OuterFilter, MaxResults);

        TArray<TSharedPtr<FJsonValue>> Values;
        Values.Reserve(Objects.Num());
        for (const FDccMcpObjectDescriptor& Object : Objects)
        {
            Values.Add(MakeShared<FJsonValueObject>(Object.ToJson()));
        }

        TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
        Result->SetArrayField(TEXT("objects"), Values);
        return Result;
    }

    if (Method == TEXT("describe_object"))
    {
        return FDccMcpReflection::DescribeObject(
            ReadString(Params, TEXT("object_path")),
            ReadBool(Params, TEXT("include_properties"), true),
            ReadBool(Params, TEXT("include_functions"), true))
            .ToJson();
    }

    if (Method == TEXT("get_property"))
    {
        return FDccMcpReflection::GetProperty(
            ReadString(Params, TEXT("object_path")),
            ReadString(Params, TEXT("property_name")));
    }

    if (Method == TEXT("get_properties"))
    {
        TArray<FString> PropertyNames;
        const TArray<TSharedPtr<FJsonValue>>* Names = nullptr;
        if (Params.IsValid() && Params->TryGetArrayField(TEXT("property_names"), Names) && Names != nullptr)
        {
            PropertyNames.Reserve(Names->Num());
            for (const TSharedPtr<FJsonValue>& Name : *Names)
            {
                FString StringValue;
                if (!Name.IsValid() || !Name->TryGetString(StringValue))
                {
                    return MakeBridgeError(TEXT("property_names must contain only strings"));
                }
                PropertyNames.Add(MoveTemp(StringValue));
            }
        }

        TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
        Result->SetArrayField(
            TEXT("properties"),
            FDccMcpReflection::GetProperties(ReadString(Params, TEXT("object_path")), PropertyNames));
        return Result;
    }

    if (Method == TEXT("set_property"))
    {
        const TSharedPtr<FJsonValue> Value = Params.IsValid()
            ? Params->TryGetField(TEXT("value"))
            : TSharedPtr<FJsonValue>();
        if (!Value.IsValid())
        {
            return MakeBridgeError(TEXT("set_property requires a value"));
        }
        return FDccMcpReflection::SetProperty(
            ReadString(Params, TEXT("object_path")),
            ReadString(Params, TEXT("property_name")),
            Value);
    }

    if (Method == TEXT("set_properties"))
    {
        TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
        Result->SetArrayField(
            TEXT("properties"),
            FDccMcpReflection::SetProperties(
                ReadString(Params, TEXT("object_path")),
                ReadObject(Params, TEXT("properties"))));
        return Result;
    }

    if (Method == TEXT("call_function"))
    {
        return FDccMcpReflection::CallFunction(
            ReadString(Params, TEXT("object_path")),
            ReadString(Params, TEXT("function_name")),
            ReadObject(Params, TEXT("args")),
            ReadInteger(Params, TEXT("timeout_ms"), 10000));
    }

    return MakeBridgeError(FString::Printf(TEXT("Unknown method: %s"), *Method));
}

void CompleteJson(
    const FHttpResultCallback& OnComplete,
    const TSharedPtr<FJsonObject>& Result,
    EHttpServerResponseCodes ResponseCode = EHttpServerResponseCodes::Ok)
{
    const TSharedPtr<FJsonObject> SafeResult = Result.IsValid()
        ? Result
        : MakeBridgeError(TEXT("Bridge handler returned no result"));

    FString ResponseBody;
    TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&ResponseBody);
    if (!FJsonSerializer::Serialize(SafeResult.ToSharedRef(), Writer))
    {
        ResponseBody = TEXT("{\"success\":false,\"error\":\"Response serialization failed\"}");
        ResponseCode = EHttpServerResponseCodes::ServerError;
    }

    TUniquePtr<FHttpServerResponse> Response =
        FHttpServerResponse::Create(ResponseBody, TEXT("application/json"));
    Response->Code = ResponseCode;
    OnComplete(MoveTemp(Response));
}
} // namespace

#endif

FDccMcpBridge::FDccMcpBridge() = default;

FDccMcpBridge::~FDccMcpBridge()
{
    StopServer();
}

bool FDccMcpBridge::StartServer(int32 Port)
{
    if (bIsRunning)
    {
        UE_LOG(LogTemp, Warning, TEXT("[DccMcpBridge] Server is already running on port %d"), BoundPort);
        return false;
    }

    if (Port <= 0 || Port > 65535)
    {
        UE_LOG(LogTemp, Error, TEXT("[DccMcpBridge] Invalid port: %d"), Port);
        return false;
    }

#if (ENGINE_MAJOR_VERSION > 5) || (ENGINE_MAJOR_VERSION == 5 && ENGINE_MINOR_VERSION >= 1)
    FHttpServerModule& HttpModule = FHttpServerModule::Get();
    HttpRouter = HttpModule.GetHttpRouter(static_cast<uint32>(Port), true);
    if (!HttpRouter.IsValid())
    {
        UE_LOG(LogTemp, Error, TEXT("[DccMcpBridge] Failed to create HTTP router on port %d"), Port);
        return false;
    }

    RouteHandle = HttpRouter->BindRoute(
        FHttpPath(TEXT("/bridge")),
        EHttpServerRequestVerbs::VERB_POST,
        FHttpRequestHandler::CreateLambda([](const FHttpServerRequest& Request, const FHttpResultCallback& OnComplete)
        {
            TSharedPtr<FJsonObject> JsonBody;
            const FUTF8ToTCHAR BodyConverter(
                reinterpret_cast<const ANSICHAR*>(Request.Body.GetData()),
                Request.Body.Num());
            const FString Body(BodyConverter.Length(), BodyConverter.Get());
            const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Body);
            if (!FJsonSerializer::Deserialize(Reader, JsonBody) || !JsonBody.IsValid())
            {
                CompleteJson(
                    OnComplete,
                    MakeBridgeError(TEXT("Invalid JSON")),
                    EHttpServerResponseCodes::BadRequest);
                return true;
            }

            FString Method;
            if (!JsonBody->TryGetStringField(TEXT("method"), Method) || Method.IsEmpty())
            {
                CompleteJson(
                    OnComplete,
                    MakeBridgeError(TEXT("A non-empty method is required")),
                    EHttpServerResponseCodes::BadRequest);
                return true;
            }

            TSharedPtr<FJsonObject> Params = MakeShared<FJsonObject>();
            const TSharedPtr<FJsonObject>* ParamsField = nullptr;
            if (JsonBody->HasField(TEXT("params")))
            {
                if (!JsonBody->TryGetObjectField(TEXT("params"), ParamsField) || ParamsField == nullptr || !ParamsField->IsValid())
                {
                    CompleteJson(
                        OnComplete,
                        MakeBridgeError(TEXT("params must be an object")),
                        EHttpServerResponseCodes::BadRequest);
                    return true;
                }
                Params = *ParamsField;
            }

            FHttpResultCallback Completion = OnComplete;
            AsyncTask(
                ENamedThreads::GameThread,
                [Method = MoveTemp(Method), Params = MoveTemp(Params), Completion = MoveTemp(Completion)]() mutable
                {
                    CompleteJson(Completion, DispatchOnGameThread(Method, Params));
                });
            return true;
        }));

    if (!RouteHandle.IsValid())
    {
        UE_LOG(LogTemp, Error, TEXT("[DccMcpBridge] Failed to bind /bridge on port %d"), Port);
        HttpRouter.Reset();
        return false;
    }

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
    if (!bIsRunning)
    {
        return;
    }

#if (ENGINE_MAJOR_VERSION > 5) || (ENGINE_MAJOR_VERSION == 5 && ENGINE_MINOR_VERSION >= 1)
    if (HttpRouter.IsValid() && RouteHandle.IsValid())
    {
        HttpRouter->UnbindRoute(RouteHandle);
    }
    RouteHandle.Reset();
    HttpRouter.Reset();
#endif

    BoundPort = 0;
    bIsRunning = false;
    UE_LOG(LogTemp, Log, TEXT("[DccMcpBridge] Server stopped."));
}
