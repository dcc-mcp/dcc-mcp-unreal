// Copyright (c) dcc-mcp contributors. All Rights Reserved.
// SPDX-License-Identifier: MIT

#include "DccMcpReflection.h"
#include "DccMcpSecurity.h"
#include "EngineUtils.h"
#include "Engine/World.h"
#include "Engine/Engine.h"
#include "GameFramework/Actor.h"
#include "Editor.h"
#include "EditorActorFolders.h"
#include "Subsystems/EditorActorSubsystem.h"
#include "UObject/StructOnScope.h"
#include "UObject/UnrealType.h"

// ── Json helpers ────────────────────────────────────────────────────────────

static TSharedPtr<FJsonObject> MakeJsonError(const FString& Message)
{
    TSharedPtr<FJsonObject> Obj = MakeShareable(new FJsonObject());
    Obj->SetBoolField(TEXT("success"), false);
    Obj->SetStringField(TEXT("error"), Message);
    return Obj;
}

static TSharedPtr<FJsonObject> MakeJsonSuccess()
{
    TSharedPtr<FJsonObject> Obj = MakeShareable(new FJsonObject());
    Obj->SetBoolField(TEXT("success"), true);
    return Obj;
}

static bool JsonValueToImportText(
    const TSharedPtr<FJsonValue>& Value,
    FString& OutText,
    FString& OutError)
{
    if (!Value.IsValid())
    {
        OutError = TEXT("Property value is missing");
        return false;
    }

    switch (Value->Type)
    {
    case EJson::String:
        OutText = Value->AsString();
        return true;
    case EJson::Number:
        OutText = FString::SanitizeFloat(Value->AsNumber());
        return true;
    case EJson::Boolean:
        OutText = Value->AsBool() ? TEXT("True") : TEXT("False");
        return true;
    case EJson::Null:
        OutText = TEXT("None");
        return true;
    default:
        OutError = TEXT("Native property writes support only string, number, boolean, and null values");
        return false;
    }
}

// ── Property extraction ─────────────────────────────────────────────────────

TArray<FDccMcpPropertyDescriptor> FDccMcpReflection::ExtractProperties(UClass* Class, UObject* Instance)
{
    TArray<FDccMcpPropertyDescriptor> Result;

    if (!Class) return Result;

    for (TFieldIterator<FProperty> It(Class); It; ++It)
    {
        FProperty* Property = *It;
        if (!Property) continue;

        FString PropName = Property->GetName();

        // Skip denied properties
        FString DenyReason;
        if (!FDccMcpSecurity::IsPropertyReadAllowed(PropName, Class->GetPathName(), &DenyReason))
        {
            continue;
        }

        FDccMcpPropertyDescriptor Desc;
        Desc.Name = PropName;
        Desc.TypeName = Property->GetCPPType();
        Desc.Category = GuessPropertyCategory(Property);
        Desc.Flags = ExtractPropertyFlags(Property);
        Desc.bIsReadable = true;
        Desc.bIsWritable = !Property->HasAnyPropertyFlags(CPF_BlueprintReadOnly) && !Property->HasAnyPropertyFlags(CPF_EditConst);
        Desc.bIsEditorVisible = Property->HasAnyPropertyFlags(CPF_Edit);

        TSharedPtr<FJsonObject> Meta = MakeShareable(new FJsonObject());
        if (Property->HasMetaData(TEXT("DisplayName")))
        {
            Meta->SetStringField(TEXT("display_name"), Property->GetMetaData(TEXT("DisplayName")));
        }
        if (Property->HasMetaData(TEXT("ToolTip")))
        {
            Meta->SetStringField(TEXT("tooltip"), Property->GetMetaData(TEXT("ToolTip")));
        }
        if (Property->HasMetaData(TEXT("Category")))
        {
            Meta->SetStringField(TEXT("category"), Property->GetMetaData(TEXT("Category")));
        }
        Desc.Metadata = Meta;

        Result.Add(Desc);
    }

    return Result;
}

TArray<FDccMcpFunctionDescriptor> FDccMcpReflection::ExtractFunctions(UClass* Class)
{
    TArray<FDccMcpFunctionDescriptor> Result;

    if (!Class) return Result;

    for (TFieldIterator<UFunction> It(Class); It; ++It)
    {
        UFunction* Function = *It;
        if (!Function) continue;

        FString FuncName = Function->GetName();

        // Skip denied functions
        FString DenyReason;
        if (!FDccMcpSecurity::IsFunctionCallAllowed(FuncName, Class->GetPathName(), &DenyReason))
        {
            continue;
        }

        FDccMcpFunctionDescriptor Desc;
        Desc.Name = FuncName;
        Desc.bIsCallable = Function->HasAnyFunctionFlags(FUNC_BlueprintCallable) || Function->HasAnyFunctionFlags(FUNC_Exec);
        Desc.bIsStatic = Function->HasAnyFunctionFlags(FUNC_Static);
        Desc.bIsPure = Function->HasAnyFunctionFlags(FUNC_BlueprintPure);

        // Flags
        if (Function->HasAnyFunctionFlags(FUNC_BlueprintCallable)) Desc.Flags.Add(TEXT("BlueprintCallable"));
        if (Function->HasAnyFunctionFlags(FUNC_Exec)) Desc.Flags.Add(TEXT("Exec"));
        if (Function->HasAnyFunctionFlags(FUNC_Static)) Desc.Flags.Add(TEXT("Static"));
        if (Function->HasAnyFunctionFlags(FUNC_BlueprintPure)) Desc.Flags.Add(TEXT("Pure"));
        if (Function->HasAnyFunctionFlags(FUNC_BlueprintEvent)) Desc.Flags.Add(TEXT("BlueprintEvent"));

        // Return type
        if (FProperty* ReturnProp = Function->GetReturnProperty())
        {
            Desc.ReturnType = ReturnProp->GetCPPType();
        }
        else
        {
            Desc.ReturnType = TEXT("void");
        }

        // Parameters
        for (TFieldIterator<FProperty> ParamIt(Function); ParamIt; ++ParamIt)
        {
            if (ParamIt->HasAnyPropertyFlags(CPF_ReturnParm)) continue;

            TSharedPtr<FJsonObject> ParamObj = MakeShareable(new FJsonObject());
            ParamObj->SetStringField(TEXT("name"), ParamIt->GetName());
            ParamObj->SetStringField(TEXT("type"), ParamIt->GetCPPType());
            Desc.Parameters.Add(MakeShareable(new FJsonValueObject(ParamObj)));
        }

        Result.Add(Desc);
    }

    return Result;
}

FString FDccMcpReflection::GuessPropertyCategory(FProperty* Property)
{
    if (!Property) return TEXT("unknown");

    if (Property->IsA<FObjectPropertyBase>()) return TEXT("object");
    if (Property->IsA<FStructProperty>()) return TEXT("struct");
    if (Property->IsA<FArrayProperty>()) return TEXT("array");
    if (Property->IsA<FMapProperty>()) return TEXT("map");
    if (Property->IsA<FSetProperty>()) return TEXT("set");
    if (Property->IsA<FEnumProperty>() || Property->IsA<FByteProperty>()) return TEXT("enum");
    if (Property->IsA<FBoolProperty>()) return TEXT("scalar");
    if (Property->IsA<FFloatProperty>() || Property->IsA<FDoubleProperty>()) return TEXT("scalar");
    if (Property->IsA<FIntProperty>() || Property->IsA<FInt64Property>()) return TEXT("scalar");
    if (Property->IsA<FStrProperty>() || Property->IsA<FNameProperty>() || Property->IsA<FTextProperty>()) return TEXT("scalar");
    if (Property->IsA<FMulticastDelegateProperty>()) return TEXT("delegate");

    return TEXT("unknown");
}

TArray<FString> FDccMcpReflection::ExtractPropertyFlags(FProperty* Property)
{
    TArray<FString> Flags;

    if (!Property) return Flags;

    if (Property->HasAnyPropertyFlags(CPF_Edit)) Flags.Add(TEXT("EditAnywhere"));
    if (Property->HasAnyPropertyFlags(CPF_EditConst)) Flags.Add(TEXT("EditConst"));
    if (Property->HasAnyPropertyFlags(CPF_BlueprintReadOnly)) Flags.Add(TEXT("BlueprintReadOnly"));
    if (Property->HasAnyPropertyFlags(CPF_BlueprintVisible)) Flags.Add(TEXT("BlueprintVisible"));
    if (Property->HasAnyPropertyFlags(CPF_Transient)) Flags.Add(TEXT("Transient"));
    if (Property->HasAnyPropertyFlags(CPF_Config)) Flags.Add(TEXT("Config"));

    return Flags;
}

// ── Object resolution ───────────────────────────────────────────────────────

UObject* FDccMcpReflection::ResolveObject(const FString& ObjectPath)
{
    // Try loading by full path
    UObject* Obj = StaticLoadObject(UObject::StaticClass(), nullptr, *ObjectPath);
    if (Obj) return Obj;

    // Try FindObject (for objects already loaded but not in asset registry)
    Obj = StaticFindObject(UObject::StaticClass(), nullptr, *ObjectPath);
    return Obj;
}

// ── Public API implementations ──────────────────────────────────────────────

TArray<FDccMcpObjectDescriptor> FDccMcpReflection::DiscoverObjects(
    const FString& ClassFilter,
    const FString& OuterFilter,
    int32 MaxResults)
{
    TArray<FDccMcpObjectDescriptor> Results;

    // Ensure we're running in editor
#if WITH_EDITOR
    if (!GEditor) return Results;

    UWorld* World = GEditor->GetEditorWorldContext().World();
    if (!World) return Results;

    // Check class filter for denied patterns
    if (!ClassFilter.IsEmpty())
    {
        FString DenyReason;
        if (!FDccMcpSecurity::IsClassAllowed(ClassFilter, &DenyReason))
        {
            UE_LOG(LogTemp, Warning, TEXT("[DccMcpReflection] DiscoverObjects denied: %s"), *DenyReason);
            return Results;
        }
    }

    for (TActorIterator<AActor> It(World); It; ++It)
    {
        AActor* Actor = *It;
        if (!Actor) continue;

        const FString ClassPath = Actor->GetClass()->GetPathName();
        const FString OuterPath = Actor->GetOuter() ? Actor->GetOuter()->GetPathName() : TEXT("");
        FString DenyReason;
        if (!FDccMcpSecurity::IsClassAllowed(ClassPath, &DenyReason))
        {
            continue;
        }
        if (!ClassFilter.IsEmpty() && !ClassPath.MatchesWildcard(ClassFilter, ESearchCase::IgnoreCase))
        {
            continue;
        }
        if (!OuterFilter.IsEmpty() && !OuterPath.MatchesWildcard(OuterFilter, ESearchCase::IgnoreCase))
        {
            continue;
        }

        FDccMcpObjectDescriptor Desc;
        Desc.Name = Actor->GetName();
        Desc.ClassPath = ClassPath;
        Desc.OuterPath = OuterPath;
        Desc.Label = Actor->GetActorLabel();
        Desc.Tags.Reserve(Actor->Tags.Num());
        for (const FName& Tag : Actor->Tags)
        {
            Desc.Tags.Add(Tag.ToString());
        }

        TSharedPtr<FJsonObject> Meta = MakeShareable(new FJsonObject());
        Meta->SetBoolField(TEXT("is_temporarily_hidden_in_editor"), Actor->IsTemporarilyHiddenInEditor());
        Desc.Metadata = Meta;

        Results.Add(Desc);

        if (Results.Num() >= MaxResults) break;
    }
#endif

    return Results;
}

FDccMcpObjectDescriptor FDccMcpReflection::DescribeObject(
    const FString& ObjectPath,
    bool bIncludeProperties,
    bool bIncludeFunctions)
{
    FDccMcpObjectDescriptor Desc;

    UObject* Obj = ResolveObject(ObjectPath);
    if (!Obj)
    {
        Desc.Name = ObjectPath;
        TSharedPtr<FJsonObject> Meta = MakeShareable(new FJsonObject());
        Meta->SetStringField(TEXT("error"), TEXT("Object not found"));
        Desc.Metadata = Meta;
        return Desc;
    }

    UClass* Class = Obj->GetClass();
    Desc.Name = Obj->GetName();
    Desc.ClassPath = Class ? Class->GetPathName() : TEXT("");

    if (UObject* Outer = Obj->GetOuter())
    {
        Desc.OuterPath = Outer->GetPathName();
    }

    if (AActor* Actor = Cast<AActor>(Obj))
    {
        Desc.Label = Actor->GetActorLabel();
        Desc.Tags.Reserve(Actor->Tags.Num());
        for (const FName& Tag : Actor->Tags)
        {
            Desc.Tags.Add(Tag.ToString());
        }
    }

    // Security check on class
    FString DenyReason;
    if (!FDccMcpSecurity::IsClassAllowed(Desc.ClassPath, &DenyReason))
    {
        TSharedPtr<FJsonObject> Meta = MakeShareable(new FJsonObject());
        Meta->SetStringField(TEXT("error"), FString::Printf(TEXT("Class denied: %s"), *DenyReason));
        Desc.Metadata = Meta;
        return Desc;
    }

    if (bIncludeProperties)
    {
        Desc.Properties = ExtractProperties(Class, Obj);
        Desc.PropertyCount = Desc.Properties.Num();
    }

    if (bIncludeFunctions)
    {
        Desc.Functions = ExtractFunctions(Class);
        Desc.FunctionCount = Desc.Functions.Num();
    }

    return Desc;
}

TSharedPtr<FJsonObject> FDccMcpReflection::GetProperty(
    const FString& ObjectPath,
    const FString& PropertyName)
{
    UObject* Obj = ResolveObject(ObjectPath);
    if (!Obj)
    {
        return MakeJsonError(TEXT("Object not found"));
    }

    UClass* Class = Obj->GetClass();
    if (!Class)
    {
        return MakeJsonError(TEXT("Class not found"));
    }

    // Security check
    FString DenyReason;
    if (!FDccMcpSecurity::IsPropertyReadAllowed(PropertyName, Class->GetPathName(), &DenyReason))
    {
        return MakeJsonError(FString::Printf(TEXT("[SECURITY DENIED] %s"), *DenyReason));
    }

    // Read the property
    FProperty* Property = Class->FindPropertyByName(*PropertyName);
    if (!Property)
    {
        return MakeJsonError(FString::Printf(TEXT("Property %s not found"), *PropertyName));
    }

    TSharedPtr<FJsonObject> Result = MakeJsonSuccess();
    Result->SetStringField(TEXT("name"), PropertyName);
    Result->SetStringField(TEXT("type_name"), Property->GetCPPType());

    // Export to text (safe, readable, works for all property types)
    FString ValueStr;
    const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Obj);
    if (ValuePtr)
    {
        Property->ExportTextItem_Direct(ValueStr, ValuePtr, nullptr, Obj, PPF_None);
    }

    Result->SetStringField(TEXT("value"), ValueStr);
    return Result;
}

TArray<TSharedPtr<FJsonValue>> FDccMcpReflection::GetProperties(
    const FString& ObjectPath,
    const TArray<FString>& PropertyNames)
{
    TArray<TSharedPtr<FJsonValue>> Results;
    for (const FString& Name : PropertyNames)
    {
        TSharedPtr<FJsonObject> Value = GetProperty(ObjectPath, Name);
        Results.Add(MakeShareable(new FJsonValueObject(Value)));
    }
    return Results;
}

TSharedPtr<FJsonObject> FDccMcpReflection::SetProperty(
    const FString& ObjectPath,
    const FString& PropertyName,
    const TSharedPtr<FJsonValue>& Value)
{
    // GameThread gate
    {
        FString ThreadReason;
        if (!FDccMcpSecurity::IsOnGameThread(&ThreadReason))
        {
            return MakeJsonError(FString::Printf(TEXT("[SECURITY DENIED] %s"), *ThreadReason));
        }
    }

    UObject* Obj = ResolveObject(ObjectPath);
    if (!Obj)
    {
        return MakeJsonError(TEXT("Object not found"));
    }

    UClass* Class = Obj->GetClass();
    if (!Class)
    {
        return MakeJsonError(TEXT("Class not found"));
    }

    // Security check
    FString DenyReason;
    if (!FDccMcpSecurity::IsPropertyWriteAllowed(PropertyName, Class->GetPathName(), &DenyReason))
    {
        return MakeJsonError(FString::Printf(TEXT("[SECURITY DENIED] %s"), *DenyReason));
    }

    // Write the property
    FProperty* Property = Class->FindPropertyByName(*PropertyName);
    if (!Property)
    {
        return MakeJsonError(FString::Printf(TEXT("Property %s not found"), *PropertyName));
    }

    FString ValueStr;
    FString ConversionError;
    if (!JsonValueToImportText(Value, ValueStr, ConversionError))
    {
        return MakeJsonError(ConversionError);
    }

    void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Obj);
    if (!ValuePtr)
    {
        return MakeJsonError(TEXT("Cannot get property value pointer"));
    }

#if WITH_EDITOR
    Obj->Modify();
#endif

    if (Property->ImportText_Direct(*ValueStr, ValuePtr, Obj, PPF_None) == nullptr)
    {
        return MakeJsonError(FString::Printf(TEXT("Failed to import value for property %s"), *PropertyName));
    }

#if WITH_EDITOR
    FPropertyChangedEvent ChangedEvent(Property, EPropertyChangeType::ValueSet);
    Obj->PostEditChangeProperty(ChangedEvent);
#endif

    TSharedPtr<FJsonObject> Result = MakeJsonSuccess();
    Result->SetStringField(TEXT("name"), PropertyName);
    Result->SetStringField(TEXT("type_name"), Property->GetCPPType());
    return Result;
}

TArray<TSharedPtr<FJsonValue>> FDccMcpReflection::SetProperties(
    const FString& ObjectPath,
    const TSharedPtr<FJsonObject>& Properties)
{
    TArray<TSharedPtr<FJsonValue>> Results;
    if (!Properties.IsValid()) return Results;

    for (const auto& Pair : Properties->Values)
    {
        const FString PropertyName(Pair.Key.Len(), *Pair.Key);
        TSharedPtr<FJsonObject> Result = SetProperty(ObjectPath, PropertyName, Pair.Value);
        Results.Add(MakeShareable(new FJsonValueObject(Result)));
    }
    return Results;
}

TSharedPtr<FJsonObject> FDccMcpReflection::CallFunction(
    const FString& ObjectPath,
    const FString& FunctionName,
    const TSharedPtr<FJsonObject>& Args,
    int32 TimeoutMs)
{
    // GameThread gate
    {
        FString ThreadReason;
        if (!FDccMcpSecurity::IsOnGameThread(&ThreadReason))
        {
            return MakeJsonError(FString::Printf(TEXT("[SECURITY DENIED] %s"), *ThreadReason));
        }
    }

    UObject* Obj = ResolveObject(ObjectPath);
    if (!Obj)
    {
        return MakeJsonError(TEXT("Object not found"));
    }

    UClass* Class = Obj->GetClass();
    if (!Class)
    {
        return MakeJsonError(TEXT("Class not found"));
    }

    // Security check
    FString DenyReason;
    if (!FDccMcpSecurity::IsFunctionCallAllowed(FunctionName, Class->GetPathName(), &DenyReason))
    {
        return MakeJsonError(FString::Printf(TEXT("[SECURITY DENIED] %s"), *DenyReason));
    }

    // Find function
    UFunction* Function = Class->FindFunctionByName(*FunctionName);
    if (!Function)
    {
        return MakeJsonError(FString::Printf(TEXT("Function %s not found"), *FunctionName));
    }

    if (!Function->HasAnyFunctionFlags(FUNC_BlueprintCallable) && !Function->HasAnyFunctionFlags(FUNC_Exec))
    {
        return MakeJsonError(FString::Printf(TEXT("Function %s is not BlueprintCallable or Exec"), *FunctionName));
    }

    if ((Args.IsValid() && Args->Values.Num() > 0))
    {
        return MakeJsonError(TEXT("Native bridge function arguments are not supported; use Unreal Python direct mode"));
    }

    for (TFieldIterator<FProperty> ParamIt(Function); ParamIt; ++ParamIt)
    {
        if (ParamIt->HasAnyPropertyFlags(CPF_Parm) && !ParamIt->HasAnyPropertyFlags(CPF_ReturnParm))
        {
            return MakeJsonError(TEXT("Native bridge supports only zero-argument UFunctions; use Unreal Python direct mode"));
        }
    }

    if (TimeoutMs <= 0)
    {
        return MakeJsonError(TEXT("timeout_ms must be greater than zero"));
    }

    FStructOnScope FunctionParams(Function);
    if (!FunctionParams.IsValid())
    {
        return MakeJsonError(TEXT("Failed to allocate UFunction parameters"));
    }

    FDateTime StartTime = FDateTime::UtcNow();
    Obj->ProcessEvent(Function, FunctionParams.GetStructMemory());

    TSharedPtr<FJsonObject> Result = MakeJsonSuccess();
    Result->SetStringField(TEXT("function_name"), FunctionName);

    if (FProperty* ReturnProperty = Function->GetReturnProperty())
    {
        const void* ReturnValue = ReturnProperty->ContainerPtrToValuePtr<void>(FunctionParams.GetStructMemory());
        FString ReturnText;
        ReturnProperty->ExportTextItem_Direct(ReturnText, ReturnValue, nullptr, Obj, PPF_None);
        Result->SetStringField(TEXT("return_value"), ReturnText);
    }

    FTimespan Elapsed = FDateTime::UtcNow() - StartTime;
    Result->SetNumberField(TEXT("execution_time_ms"), Elapsed.GetTotalMilliseconds());
    return Result;
}

// ── Json serialization helpers ──────────────────────────────────────────────

TSharedPtr<FJsonObject> FDccMcpObjectDescriptor::ToJson() const
{
    TSharedPtr<FJsonObject> Obj = MakeShareable(new FJsonObject());
    Obj->SetStringField(TEXT("name"), Name);
    Obj->SetStringField(TEXT("class_path"), ClassPath);
    Obj->SetStringField(TEXT("outer_path"), OuterPath);
    Obj->SetStringField(TEXT("label"), Label);
    Obj->SetNumberField(TEXT("property_count"), PropertyCount);
    Obj->SetNumberField(TEXT("function_count"), FunctionCount);

    TArray<TSharedPtr<FJsonValue>> PropsArr;
    for (const auto& Prop : Properties)
    {
        PropsArr.Add(MakeShareable(new FJsonValueObject(Prop.ToJson())));
    }
    Obj->SetArrayField(TEXT("properties"), PropsArr);

    TArray<TSharedPtr<FJsonValue>> FuncsArr;
    for (const auto& Func : Functions)
    {
        FuncsArr.Add(MakeShareable(new FJsonValueObject(Func.ToJson())));
    }
    Obj->SetArrayField(TEXT("functions"), FuncsArr);

    TArray<TSharedPtr<FJsonValue>> TagsArr;
    for (const auto& Tag : Tags)
    {
        TagsArr.Add(MakeShareable(new FJsonValueString(Tag)));
    }
    Obj->SetArrayField(TEXT("tags"), TagsArr);

    if (Metadata.IsValid())
    {
        Obj->SetObjectField(TEXT("metadata"), Metadata);
    }

    return Obj;
}

TSharedPtr<FJsonObject> FDccMcpPropertyDescriptor::ToJson() const
{
    TSharedPtr<FJsonObject> Obj = MakeShareable(new FJsonObject());
    Obj->SetStringField(TEXT("name"), Name);
    Obj->SetStringField(TEXT("type_name"), TypeName);
    Obj->SetStringField(TEXT("category"), Category);
    Obj->SetBoolField(TEXT("is_readable"), bIsReadable);
    Obj->SetBoolField(TEXT("is_writable"), bIsWritable);
    Obj->SetBoolField(TEXT("is_editor_visible"), bIsEditorVisible);

    TArray<TSharedPtr<FJsonValue>> FlagsArr;
    for (const auto& Flag : Flags)
    {
        FlagsArr.Add(MakeShareable(new FJsonValueString(Flag)));
    }
    Obj->SetArrayField(TEXT("flags"), FlagsArr);

    if (Metadata.IsValid())
    {
        Obj->SetObjectField(TEXT("metadata"), Metadata);
    }

    return Obj;
}

TSharedPtr<FJsonObject> FDccMcpFunctionDescriptor::ToJson() const
{
    TSharedPtr<FJsonObject> Obj = MakeShareable(new FJsonObject());
    Obj->SetStringField(TEXT("name"), Name);
    Obj->SetStringField(TEXT("return_type"), ReturnType);
    Obj->SetBoolField(TEXT("is_callable"), bIsCallable);
    Obj->SetBoolField(TEXT("is_static"), bIsStatic);
    Obj->SetBoolField(TEXT("is_pure"), bIsPure);

    Obj->SetArrayField(TEXT("parameters"), Parameters);

    TArray<TSharedPtr<FJsonValue>> FlagsArr;
    for (const auto& Flag : Flags)
    {
        FlagsArr.Add(MakeShareable(new FJsonValueString(Flag)));
    }
    Obj->SetArrayField(TEXT("flags"), FlagsArr);

    if (Metadata.IsValid())
    {
        Obj->SetObjectField(TEXT("metadata"), Metadata);
    }

    return Obj;
}
