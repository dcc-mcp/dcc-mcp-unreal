#include "Editor.h"
#include "Runtime/Launch/Resources/Version.h"
#if ENGINE_MAJOR_VERSION >= 5
#include "AssetRegistry/AssetRegistryModule.h"
#else
#include "AssetRegistryModule.h"
#endif
#include "Components/ActorComponent.h"
#include "Engine/Blueprint.h"
#include "Engine/SCS_Node.h"
#include "Engine/SimpleConstructionScript.h"
#include "EngineUtils.h"
#include "HAL/PlatformProcess.h"
#include "HAL/PlatformMisc.h"
#include "Interfaces/IPv4/IPv4Address.h"
#include "IPAddress.h"
#include "Json.h"
#include "Modules/ModuleManager.h"
#include "Misc/PackageName.h"
#include "SocketSubsystem.h"
#include "Sockets.h"
#include "ScopedTransaction.h"
#include "Tickable.h"
#include "UObject/UObjectGlobals.h"
#include "FileHelpers.h"
#include "Kismet2/KismetEditorUtilities.h"

DEFINE_LOG_CATEGORY_STATIC(LogDccMcpUnreal, Log, All);

class FDccMcpUnrealModule : public IModuleInterface
{
public:
	virtual void StartupModule() override
	{
		const FString RuntimeMode = GetEnvironmentVariable(TEXT("DCC_MCP_UNREAL_RUNTIME"));
#if ENGINE_MAJOR_VERSION >= 5
		const bool bAutoPythonSupported = true;
#else
		const bool bAutoPythonSupported = false;
#endif
		const bool bPythonRuntime = RuntimeMode.Equals(TEXT("python"), ESearchCase::IgnoreCase) ||
			(bAutoPythonSupported &&
			 (RuntimeMode.IsEmpty() || RuntimeMode.Equals(TEXT("auto"), ESearchCase::IgnoreCase)) &&
			 FModuleManager::Get().IsModuleLoaded(FName(TEXT("PythonScriptPlugin"))));
		if (bPythonRuntime)
		{
			UE_LOG(LogDccMcpUnreal, Display, TEXT("PythonScriptPlugin is active; skipping the standalone sidecar"));
			return;
		}

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
#if ENGINE_MAJOR_VERSION >= 5
				TickHandle = FTSTicker::GetCoreTicker().AddTicker(FTickerDelegate::CreateRaw(this, &FDccMcpUnrealModule::Tick));
#else
				TickHandle = FTicker::GetCoreTicker().AddTicker(FTickerDelegate::CreateRaw(this, &FDccMcpUnrealModule::Tick));
#endif
				UE_LOG(LogDccMcpUnreal, Display, TEXT("UE native bridge listening on qtserver://127.0.0.1:%d"), Port);
				return;
			}
		}
		UE_LOG(LogDccMcpUnreal, Error, TEXT("Unable to bind a native bridge port"));
	}

	virtual void ShutdownModule() override
	{
		if (TickHandle.IsValid())
		{
#if ENGINE_MAJOR_VERSION >= 5
			FTSTicker::GetCoreTicker().RemoveTicker(TickHandle);
#else
			FTicker::GetCoreTicker().RemoveTicker(TickHandle);
#endif
		}
		CloseSocket(Client);
		CloseSocket(Listener);
		if (Sidecar.IsValid()) FPlatformProcess::TerminateProc(Sidecar, true);
	}

private:
	FString GetEnvironmentVariable(const TCHAR* Name) const
	{
#if ENGINE_MAJOR_VERSION >= 5
		return FPlatformMisc::GetEnvironmentVariable(Name);
#else
		TCHAR Buffer[1024] = { 0 };
		FPlatformMisc::GetEnvironmentVariable(Name, Buffer, 1024);
		return FString(Buffer);
#endif
	}

	void StartSidecar(int32 BoundPort)
	{
		FString Executable = GetEnvironmentVariable(TEXT("DCC_MCP_SERVER_EXECUTABLE"));
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
		if (Action == TEXT("unreal_level__save_level")) return SaveLevel(Id, Args ? *Args : nullptr);
		if (Action == TEXT("unreal_assets__list_assets")) return ListAssets(Id, Args ? *Args : nullptr);
		if (Action == TEXT("unreal_assets__create_blueprint")) return CreateBlueprintAsset(Id, Args ? *Args : nullptr, true);
		if (Action == TEXT("unreal_blueprints__create_blueprint_class")) return CreateBlueprintAsset(Id, Args ? *Args : nullptr, false);
		if (Action == TEXT("unreal_blueprints__add_component_to_blueprint")) return AddBlueprintComponent(Id, Args ? *Args : nullptr);
		if (Action == TEXT("unreal_blueprints__compile_blueprint")) return CompileBlueprint(Id, Args ? *Args : nullptr);
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

	void ListAssets(const FString& Id, const TSharedPtr<FJsonObject>& Args)
	{
		const FString Directory = Args.IsValid() && Args->HasTypedField<EJson::String>(TEXT("directory_path"))
			? Args->GetStringField(TEXT("directory_path")) : TEXT("/Game");
		const bool bRecursive = !Args.IsValid() || !Args->HasTypedField<EJson::Boolean>(TEXT("recursive")) ||
			Args->GetBoolField(TEXT("recursive"));
		const FString ClassFilter = Args.IsValid() && Args->HasTypedField<EJson::String>(TEXT("asset_class_filter"))
			? Args->GetStringField(TEXT("asset_class_filter")) : TEXT("");
		TArray<FAssetData> Found;
		FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry"))
			.Get().GetAssetsByPath(FName(*Directory), Found, bRecursive);
		TArray<TSharedPtr<FJsonValue> > Assets;
		for (const FAssetData& Asset : Found)
		{
#if ENGINE_MAJOR_VERSION >= 5
			const FString ClassName = Asset.AssetClassPath.GetAssetName().ToString();
			const FString ObjectPath = Asset.GetObjectPathString();
#else
			const FString ClassName = Asset.AssetClass.ToString();
			const FString ObjectPath = Asset.ObjectPath.ToString();
#endif
			if (!ClassFilter.IsEmpty() && !ClassName.Contains(ClassFilter)) continue;
			TSharedRef<FJsonObject> Item = MakeShareable(new FJsonObject());
			Item->SetStringField(TEXT("asset_name"), Asset.AssetName.ToString());
			Item->SetStringField(TEXT("asset_class"), ClassName);
			Item->SetStringField(TEXT("object_path"), ObjectPath);
			Assets.Add(MakeShareable(new FJsonValueObject(Item)));
		}
		TSharedRef<FJsonObject> Data = MakeShareable(new FJsonObject());
		Data->SetArrayField(TEXT("assets"), Assets);
		Data->SetNumberField(TEXT("count"), Assets.Num());
		SendResult(Id, Data);
	}

	FString BlueprintObjectPath(const FString& Name, const FString& PackagePath = TEXT("/Game/Blueprints")) const
	{
		if (Name.Contains(TEXT("."))) return Name;
		const FString AssetName = FPackageName::GetShortName(Name);
		const FString Package = Name.StartsWith(TEXT("/Game/")) ? Name : PackagePath / Name;
		return Package + TEXT(".") + AssetName;
	}

	UBlueprint* LoadBlueprint(const FString& Name) const
	{
		return Cast<UBlueprint>(StaticLoadObject(UBlueprint::StaticClass(), nullptr, *BlueprintObjectPath(Name)));
	}

	bool SaveBlueprint(UBlueprint* Blueprint) const
	{
		FKismetEditorUtilities::CompileBlueprint(Blueprint);
		Blueprint->MarkPackageDirty();
		TArray<UPackage*> Packages;
		Packages.Add(Blueprint->GetOutermost());
		return FEditorFileUtils::PromptForCheckoutAndSave(Packages, false, false) == FEditorFileUtils::PR_Success;
	}

	void CreateBlueprintAsset(const FString& Id, const TSharedPtr<FJsonObject>& Args, bool bAssetContract)
	{
		if (!Args.IsValid() || !Args->HasTypedField<EJson::String>(TEXT("blueprint_name")))
			return SendError(Id, TEXT("invalid-params"), TEXT("blueprint_name is required"));
		const FString Name = Args->GetStringField(TEXT("blueprint_name"));
		const FString PackagePath = Args->HasTypedField<EJson::String>(bAssetContract ? TEXT("destination_path") : TEXT("package_path"))
			? Args->GetStringField(bAssetContract ? TEXT("destination_path") : TEXT("package_path")) : TEXT("/Game/Blueprints");
		const FString Parent = Args->HasTypedField<EJson::String>(bAssetContract ? TEXT("parent_class_path") : TEXT("parent_class"))
			? Args->GetStringField(bAssetContract ? TEXT("parent_class_path") : TEXT("parent_class")) : TEXT("Actor");
		const FString ParentPath = Parent.StartsWith(TEXT("/")) ? Parent : FString::Printf(TEXT("/Script/Engine.%s"), *Parent);
		UClass* ParentClass = StaticLoadClass(UObject::StaticClass(), nullptr, *ParentPath);
		if (!ParentClass) return SendError(Id, TEXT("class-not-found"), FString::Printf(TEXT("Unable to load %s"), *ParentPath));
		const FString FullPackagePath = PackagePath / Name;
#if ENGINE_MAJOR_VERSION >= 5
		UPackage* Package = CreatePackage(*FullPackagePath);
#else
		UPackage* Package = CreatePackage(nullptr, *FullPackagePath);
#endif
		if (!Package) return SendError(Id, TEXT("create-failed"), TEXT("Unable to create the Blueprint package"));
		UBlueprint* Blueprint = FKismetEditorUtilities::CreateBlueprint(
			ParentClass, Package, FName(*Name), BPTYPE_Normal, UBlueprint::StaticClass(),
			UBlueprintGeneratedClass::StaticClass(), FName(TEXT("DccMcpUnreal")));
		if (!Blueprint) return SendError(Id, TEXT("create-failed"), TEXT("Unable to create the Blueprint"));
		FAssetRegistryModule::AssetCreated(Blueprint);
		if (!SaveBlueprint(Blueprint)) return SendError(Id, TEXT("save-failed"), TEXT("Blueprint save was cancelled or failed"));
		TSharedRef<FJsonObject> Data = MakeShareable(new FJsonObject());
		Data->SetStringField(TEXT("blueprint_path"), BlueprintObjectPath(Name, PackagePath));
		SendResult(Id, Data);
	}

	void AddBlueprintComponent(const FString& Id, const TSharedPtr<FJsonObject>& Args)
	{
		if (!Args.IsValid() || !Args->HasTypedField<EJson::String>(TEXT("blueprint_name")) ||
			!Args->HasTypedField<EJson::String>(TEXT("component_type")) ||
			!Args->HasTypedField<EJson::String>(TEXT("component_name")))
			return SendError(Id, TEXT("invalid-params"), TEXT("blueprint_name, component_type, and component_name are required"));
		UBlueprint* Blueprint = LoadBlueprint(Args->GetStringField(TEXT("blueprint_name")));
		if (!Blueprint) return SendError(Id, TEXT("blueprint-not-found"), TEXT("Blueprint was not found"));
		const FString Type = Args->GetStringField(TEXT("component_type"));
		UClass* ComponentClass = StaticLoadClass(UActorComponent::StaticClass(), nullptr, *FString::Printf(TEXT("/Script/Engine.%s"), *Type));
		if (!ComponentClass) return SendError(Id, TEXT("class-not-found"), FString::Printf(TEXT("Unable to load component type %s"), *Type));
		USCS_Node* Node = Blueprint->SimpleConstructionScript->CreateNode(ComponentClass, FName(*Args->GetStringField(TEXT("component_name"))));
		Blueprint->SimpleConstructionScript->AddNode(Node);
		if (!SaveBlueprint(Blueprint)) return SendError(Id, TEXT("save-failed"), TEXT("Blueprint save was cancelled or failed"));
		TSharedRef<FJsonObject> Data = MakeShareable(new FJsonObject());
		Data->SetStringField(TEXT("component_name"), Node->GetVariableName().ToString());
		SendResult(Id, Data);
	}

	void CompileBlueprint(const FString& Id, const TSharedPtr<FJsonObject>& Args)
	{
		if (!Args.IsValid() || !Args->HasTypedField<EJson::String>(TEXT("blueprint_name")))
			return SendError(Id, TEXT("invalid-params"), TEXT("blueprint_name is required"));
		UBlueprint* Blueprint = LoadBlueprint(Args->GetStringField(TEXT("blueprint_name")));
		if (!Blueprint) return SendError(Id, TEXT("blueprint-not-found"), TEXT("Blueprint was not found"));
		if (!SaveBlueprint(Blueprint)) return SendError(Id, TEXT("save-failed"), TEXT("Blueprint save was cancelled or failed"));
		TSharedRef<FJsonObject> Data = MakeShareable(new FJsonObject());
		Data->SetStringField(TEXT("blueprint_name"), Blueprint->GetName());
		Data->SetBoolField(TEXT("compiled"), true);
		SendResult(Id, Data);
	}

	void SaveLevel(const FString& Id, const TSharedPtr<FJsonObject>& Args)
	{
		const bool bAllDirty = Args.IsValid() && Args->HasTypedField<EJson::Boolean>(TEXT("save_all_dirty")) &&
			Args->GetBoolField(TEXT("save_all_dirty"));
		const bool bSaved = bAllDirty
			? FEditorFileUtils::SaveDirtyPackages(true, true, true, false, false, false)
			: FEditorFileUtils::SaveCurrentLevel();
		if (!bSaved) return SendError(Id, TEXT("save-failed"), TEXT("Level save was cancelled or failed"));
		TSharedRef<FJsonObject> Data = MakeShareable(new FJsonObject());
		Data->SetBoolField(TEXT("saved"), true);
		Data->SetBoolField(TEXT("saved_all_dirty"), bAllDirty);
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
#if ENGINE_MAJOR_VERSION >= 5
	FTSTicker::FDelegateHandle TickHandle;
#else
	FDelegateHandle TickHandle;
#endif
	int32 Port = 0;
};

IMPLEMENT_MODULE(FDccMcpUnrealModule, DccMcpUnreal)
