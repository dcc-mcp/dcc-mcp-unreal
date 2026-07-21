#include "Editor.h"
#include "EngineUtils.h"
#include "HAL/PlatformProcess.h"
#include "HAL/PlatformMisc.h"
#include "Interfaces/IPv4/IPv4Address.h"
#include "IPAddress.h"
#include "Json.h"
#include "Modules/ModuleManager.h"
#include "SocketSubsystem.h"
#include "Sockets.h"
#include "ScopedTransaction.h"
#include "Tickable.h"
#include "UObject/UObjectGlobals.h"

DEFINE_LOG_CATEGORY_STATIC(LogDccMcpUnreal, Log, All);

class FDccMcpUnrealModule : public IModuleInterface
{
public:
	virtual void StartupModule() override
	{
		Listener = ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM)->CreateSocket(NAME_Stream, TEXT("DccMcpUnreal"), false);
		TSharedRef<FInternetAddr> Address = ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM)->CreateInternetAddr();
		bool bValid = false;
		Address->SetIp(TEXT("127.0.0.1"), bValid);
		for (Port = 18765; bValid && Port <= 18775; ++Port)
		{
			Address->SetPort(Port);
			if (Listener->Bind(*Address))
			{
				Listener->SetNonBlocking(true);
				Listener->Listen(1);
				StartSidecar(Port);
				TickHandle = FTicker::GetCoreTicker().AddTicker(FTickerDelegate::CreateRaw(this, &FDccMcpUnrealModule::Tick));
				UE_LOG(LogDccMcpUnreal, Display, TEXT("UE native bridge listening on qtserver://127.0.0.1:%d"), Port);
				return;
			}
		}
		UE_LOG(LogDccMcpUnreal, Error, TEXT("Unable to bind a native bridge port"));
	}

	virtual void ShutdownModule() override
	{
		if (TickHandle.IsValid()) FTicker::GetCoreTicker().RemoveTicker(TickHandle);
		CloseSocket(Client);
		CloseSocket(Listener);
		if (Sidecar.IsValid()) FPlatformProcess::TerminateProc(Sidecar, true);
	}

private:
	void StartSidecar(int32 BoundPort)
	{
#if ENGINE_MAJOR_VERSION >= 5
		// UE 5.0+: FString-returning GetEnvironmentVariable (buffer form deprecated in 5.7)
		FString Executable = FPlatformMisc::GetEnvironmentVariable(TEXT("DCC_MCP_SERVER_EXECUTABLE"));
#else
		// UE 4.18: buffer-based form only
		TCHAR ExecutableBuffer[1024] = { 0 };
		FPlatformMisc::GetEnvironmentVariable(TEXT("DCC_MCP_SERVER_EXECUTABLE"), ExecutableBuffer, 1024);
		FString Executable(ExecutableBuffer);
#endif
		if (Executable.IsEmpty()) Executable = TEXT("dcc-mcp-server.exe");
		const FString Args = FString::Printf(
			TEXT("sidecar --dcc unreal --host-rpc qtserver://127.0.0.1:%d --watch-pid %u --display-name UnrealEditor --adapter-version 0.2.0 --no-ensure-gateway"),
			BoundPort, FPlatformProcess::GetCurrentProcessId());
		Sidecar = FPlatformProcess::CreateProc(*Executable, *Args, true, true, true, nullptr, 0, nullptr, nullptr);
		if (!Sidecar.IsValid()) UE_LOG(LogDccMcpUnreal, Error, TEXT("Failed to launch %s"), *Executable);
	}

	bool Tick(float)
	{
		if (!Client && Listener) Client = Listener->Accept(TEXT("DccMcpSidecar"));
		if (!Client) return true;

		uint32 Pending = 0;
		while (Client->HasPendingData(Pending))
		{
			const int32 Offset = ReceiveBuffer.Num();
			ReceiveBuffer.AddUninitialized(FMath::Min(Pending, 65536u));
			int32 Read = 0;
			if (!Client->Recv(ReceiveBuffer.GetData() + Offset, ReceiveBuffer.Num() - Offset, Read) || Read <= 0)
			{
				ReceiveBuffer.SetNum(Offset);
				CloseSocket(Client);
				return true;
			}
			ReceiveBuffer.SetNum(Offset + Read);
		}

		for (int32 Newline = ReceiveBuffer.Find('\n'); Newline != INDEX_NONE; Newline = ReceiveBuffer.Find('\n'))
		{
			FUTF8ToTCHAR Text(reinterpret_cast<const ANSICHAR*>(ReceiveBuffer.GetData()), Newline);
			HandleLine(FString(Text.Length(), Text.Get()));
			// RemoveAt(Index, Count, bAllowShrinking) 3-arg form is deprecated in UE 5.7
			ReceiveBuffer.RemoveAt(0, Newline + 1);
		}
		return true;
	}

	void HandleLine(const FString& Line)
	{
		TSharedPtr<FJsonObject> Request;
		const TSharedRef<TJsonReader<> > Reader = TJsonReaderFactory<>::Create(Line);
		if (!FJsonSerializer::Deserialize(Reader, Request) || !Request.IsValid()) return SendError(TEXT("null"), TEXT("invalid-json"), TEXT("Request is not valid JSON"));

		const FString Id = Request->GetStringField(TEXT("id"));
		const TSharedPtr<FJsonObject>* Params = nullptr;
		if (!Request->TryGetObjectField(TEXT("params"), Params) || !Params || !Params->IsValid()) return SendError(Id, TEXT("invalid-params"), TEXT("Missing params"));
		const FString Action = (*Params)->GetStringField(TEXT("action"));
		const TSharedPtr<FJsonObject>* Args = nullptr;
		(*Params)->TryGetObjectField(TEXT("args"), Args);

		if (Action == TEXT("unreal_actors__list_actors")) return SendActors(Id, Args ? *Args : nullptr);
		if (Action == TEXT("unreal_actors__spawn_actor")) return SpawnActor(Id, Args ? *Args : nullptr);
		if (Action == TEXT("unreal_actors__delete_actor")) return DeleteActor(Id, Args ? *Args : nullptr);
		if (Action == TEXT("unreal_actors__get_actor_transform")) return GetActorTransform(Id, Args ? *Args : nullptr);
		if (Action == TEXT("unreal_actors__set_actor_transform")) return SetActorTransform(Id, Args ? *Args : nullptr);
		if (Action == TEXT("unreal_level__get_level_info")) return SendLevelInfo(Id);
		SendError(Id, TEXT("unknown-action"), FString::Printf(TEXT("UE4.18 native bridge does not implement %s"), *Action));
	}

	UWorld* EditorWorld() const
	{
		return GEditor ? GEditor->GetEditorWorldContext().World() : nullptr;
	}

	AActor* FindActor(const TSharedPtr<FJsonObject>& Args) const
	{
		if (!Args.IsValid() || !Args->HasTypedField<EJson::String>(TEXT("actor_name"))) return nullptr;
		if (UWorld* World = EditorWorld())
		{
			const FString Name = Args->GetStringField(TEXT("actor_name"));
			for (TActorIterator<AActor> It(World); It; ++It) if (It->GetName() == Name) return *It;
		}
		return nullptr;
	}

	TSharedRef<FJsonObject> ActorData(AActor* Actor) const
	{
		TSharedRef<FJsonObject> Data = MakeShareable(new FJsonObject());
		const FVector Location = Actor->GetActorLocation();
		const FRotator Rotation = Actor->GetActorRotation();
		const FVector Scale = Actor->GetActorScale3D();
		Data->SetStringField(TEXT("actor_name"), Actor->GetName());
		Data->SetStringField(TEXT("actor_class"), Actor->GetClass()->GetName());
		Data->SetNumberField(TEXT("location_x"), Location.X);
		Data->SetNumberField(TEXT("location_y"), Location.Y);
		Data->SetNumberField(TEXT("location_z"), Location.Z);
		Data->SetNumberField(TEXT("rotation_pitch"), Rotation.Pitch);
		Data->SetNumberField(TEXT("rotation_yaw"), Rotation.Yaw);
		Data->SetNumberField(TEXT("rotation_roll"), Rotation.Roll);
		Data->SetNumberField(TEXT("scale_x"), Scale.X);
		Data->SetNumberField(TEXT("scale_y"), Scale.Y);
		Data->SetNumberField(TEXT("scale_z"), Scale.Z);
		return Data;
	}

	void SpawnActor(const FString& Id, const TSharedPtr<FJsonObject>& Args)
	{
		UWorld* World = EditorWorld();
		if (!World || !Args.IsValid()) return SendError(Id, TEXT("invalid-params"), TEXT("Editor world and args are required"));
		const FString ClassPath = Args->HasTypedField<EJson::String>(TEXT("actor_class")) ? Args->GetStringField(TEXT("actor_class")) : TEXT("/Script/Engine.StaticMeshActor");
		UClass* ActorClass = StaticLoadClass(AActor::StaticClass(), nullptr, *ClassPath);
		if (!ActorClass) return SendError(Id, TEXT("class-not-found"), FString::Printf(TEXT("Unable to load %s"), *ClassPath));
		double X = 0, Y = 0, Z = 0;
		Args->TryGetNumberField(TEXT("location_x"), X);
		Args->TryGetNumberField(TEXT("location_y"), Y);
		Args->TryGetNumberField(TEXT("location_z"), Z);
		const FScopedTransaction Transaction(NSLOCTEXT("DccMcpUnreal", "SpawnActor", "DCC MCP Spawn Actor"));
		AActor* Actor = World->SpawnActor<AActor>(ActorClass, FVector(X, Y, Z), FRotator::ZeroRotator);
		if (!Actor) return SendError(Id, TEXT("spawn-failed"), TEXT("Unreal failed to spawn the actor"));
		if (Args->HasTypedField<EJson::String>(TEXT("label"))) Actor->SetActorLabel(Args->GetStringField(TEXT("label")));
		SendResult(Id, ActorData(Actor));
	}

	void DeleteActor(const FString& Id, const TSharedPtr<FJsonObject>& Args)
	{
		AActor* Actor = FindActor(Args);
		UWorld* World = EditorWorld();
		if (!Actor || !World) return SendError(Id, TEXT("actor-not-found"), TEXT("Actor was not found"));
		const FString Name = Actor->GetName();
		const FScopedTransaction Transaction(NSLOCTEXT("DccMcpUnreal", "DeleteActor", "DCC MCP Delete Actor"));
		if (!World->EditorDestroyActor(Actor, true)) return SendError(Id, TEXT("delete-failed"), TEXT("Unreal refused to delete the actor"));
		TSharedRef<FJsonObject> Data = MakeShareable(new FJsonObject());
		Data->SetStringField(TEXT("actor_name"), Name);
		Data->SetBoolField(TEXT("deleted"), true);
		SendResult(Id, Data);
	}

	void GetActorTransform(const FString& Id, const TSharedPtr<FJsonObject>& Args)
	{
		AActor* Actor = FindActor(Args);
		if (!Actor) return SendError(Id, TEXT("actor-not-found"), TEXT("Actor was not found"));
		SendResult(Id, ActorData(Actor));
	}

	void SetActorTransform(const FString& Id, const TSharedPtr<FJsonObject>& Args)
	{
		AActor* Actor = FindActor(Args);
		if (!Actor) return SendError(Id, TEXT("actor-not-found"), TEXT("Actor was not found"));
		FVector Location = Actor->GetActorLocation();
		FRotator Rotation = Actor->GetActorRotation();
		FVector Scale = Actor->GetActorScale3D();
		double Value = 0;
		if (Args->TryGetNumberField(TEXT("location_x"), Value)) Location.X = Value;
		if (Args->TryGetNumberField(TEXT("location_y"), Value)) Location.Y = Value;
		if (Args->TryGetNumberField(TEXT("location_z"), Value)) Location.Z = Value;
		if (Args->TryGetNumberField(TEXT("rotation_pitch"), Value)) Rotation.Pitch = Value;
		if (Args->TryGetNumberField(TEXT("rotation_yaw"), Value)) Rotation.Yaw = Value;
		if (Args->TryGetNumberField(TEXT("rotation_roll"), Value)) Rotation.Roll = Value;
		if (Args->TryGetNumberField(TEXT("scale_x"), Value)) Scale.X = Value;
		if (Args->TryGetNumberField(TEXT("scale_y"), Value)) Scale.Y = Value;
		if (Args->TryGetNumberField(TEXT("scale_z"), Value)) Scale.Z = Value;
		const FScopedTransaction Transaction(NSLOCTEXT("DccMcpUnreal", "SetActorTransform", "DCC MCP Set Actor Transform"));
		Actor->Modify();
		Actor->SetActorLocationAndRotation(Location, Rotation, false, nullptr, ETeleportType::TeleportPhysics);
		Actor->SetActorScale3D(Scale);
		SendResult(Id, ActorData(Actor));
	}

	void SendActors(const FString& Id, const TSharedPtr<FJsonObject>& Args)
	{
		const FString Filter = Args.IsValid() && Args->HasField(TEXT("actor_class_filter")) ? Args->GetStringField(TEXT("actor_class_filter")) : TEXT("");
		TArray<TSharedPtr<FJsonValue> > Actors;
		if (UWorld* World = EditorWorld())
		{
			for (TActorIterator<AActor> It(World); It; ++It)
			{
				if (!Filter.IsEmpty() && !It->GetClass()->GetName().Contains(Filter)) continue;
				TSharedRef<FJsonObject> Actor = MakeShareable(new FJsonObject());
				Actor->SetStringField(TEXT("name"), It->GetName());
				Actor->SetStringField(TEXT("class"), It->GetClass()->GetName());
				Actors.Add(MakeShareable(new FJsonValueObject(Actor)));
			}
		}
		TSharedRef<FJsonObject> Data = MakeShareable(new FJsonObject());
		Data->SetArrayField(TEXT("actors"), Actors);
		Data->SetNumberField(TEXT("count"), Actors.Num());
		SendResult(Id, Data);
	}

	void SendLevelInfo(const FString& Id)
	{
		TSharedRef<FJsonObject> Data = MakeShareable(new FJsonObject());
		UWorld* World = EditorWorld();
		Data->SetStringField(TEXT("level_name"), World ? World->GetMapName() : TEXT(""));
		Data->SetStringField(TEXT("engine_version"), FEngineVersion::Current().ToString());
		SendResult(Id, Data);
	}

	void SendResult(const FString& Id, const TSharedRef<FJsonObject>& Data)
	{
		TSharedRef<FJsonObject> Envelope = MakeShareable(new FJsonObject());
		Envelope->SetStringField(TEXT("id"), Id);
		TSharedRef<FJsonObject> Result = MakeShareable(new FJsonObject());
		Result->SetBoolField(TEXT("isError"), false);
		Result->SetObjectField(TEXT("structuredContent"), Data);
		FString DataText;
		FJsonSerializer::Serialize(Data, TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR> >::Create(&DataText));
		TSharedRef<FJsonObject> TextContent = MakeShareable(new FJsonObject());
		TextContent->SetStringField(TEXT("type"), TEXT("text"));
		TextContent->SetStringField(TEXT("text"), DataText);
		TArray<TSharedPtr<FJsonValue> > Content;
		Content.Add(MakeShareable(new FJsonValueObject(TextContent)));
		Result->SetArrayField(TEXT("content"), Content);
		Envelope->SetObjectField(TEXT("result"), Result);
		SendJson(Envelope);
	}

	void SendError(const FString& Id, const FString& Code, const FString& Message)
	{
		TSharedRef<FJsonObject> Envelope = MakeShareable(new FJsonObject());
		Envelope->SetStringField(TEXT("id"), Id);
		TSharedRef<FJsonObject> Error = MakeShareable(new FJsonObject());
		Error->SetStringField(TEXT("code"), Code);
		Error->SetStringField(TEXT("message"), Message);
		Envelope->SetObjectField(TEXT("error"), Error);
		SendJson(Envelope);
	}

	void SendJson(const TSharedRef<FJsonObject>& Object)
	{
		FString Text;
		FJsonSerializer::Serialize(Object, TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR> >::Create(&Text));
		Text.AppendChar('\n');
		FTCHARToUTF8 Utf8(*Text);
		int32 Offset = 0;
		while (Client && Offset < Utf8.Length())
		{
			int32 Sent = 0;
			if (!Client->Send(reinterpret_cast<const uint8*>(Utf8.Get()) + Offset, Utf8.Length() - Offset, Sent) || Sent <= 0) break;
			Offset += Sent;
		}
	}

	void CloseSocket(FSocket*& Socket)
	{
		if (!Socket) return;
		Socket->Close();
		ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM)->DestroySocket(Socket);
		Socket = nullptr;
	}

	FSocket* Listener = nullptr;
	FSocket* Client = nullptr;
	TArray<uint8> ReceiveBuffer;
	FProcHandle Sidecar;
	FDelegateHandle TickHandle;
	int32 Port = 0;
};

IMPLEMENT_MODULE(FDccMcpUnrealModule, DccMcpUnreal)
