// Copyright (c) dcc-mcp contributors. All Rights Reserved.
// SPDX-License-Identifier: MIT

#pragma once

#include "CoreMinimal.h"
#include "UObject/NoExportTypes.h"
#include "Dom/JsonObject.h"

/**
 * Describes a single UProperty for the Python reflection layer.
 */
struct DCCMCPUNREAL_API FDccMcpPropertyDescriptor
{
    FString Name;
    FString TypeName;
    FString Category;       // "scalar", "struct", "array", "map", "set", "object", "enum", "delegate"
    TArray<FString> Flags;  // "EditAnywhere", "BlueprintReadOnly", etc.
    bool bIsReadable = true;
    bool bIsWritable = true;
    bool bIsEditorVisible = false;
    TSharedPtr<FJsonObject> Metadata;

    TSharedPtr<FJsonObject> ToJson() const;
};

/**
 * Describes a single UFunction for the Python reflection layer.
 */
struct DCCMCPUNREAL_API FDccMcpFunctionDescriptor
{
    FString Name;
    FString ReturnType;
    TArray<TSharedPtr<FJsonValue>> Parameters;  // [{"name": "...", "type": "..."}]
    TArray<FString> Flags;                      // "BlueprintCallable", "Exec", etc.
    bool bIsCallable = true;
    bool bIsStatic = false;
    bool bIsPure = false;
    TSharedPtr<FJsonObject> Metadata;

    TSharedPtr<FJsonObject> ToJson() const;
};

/**
 * Describes a discovered UObject for the Python reflection layer.
 */
struct DCCMCPUNREAL_API FDccMcpObjectDescriptor
{
    FString Name;
    FString ClassPath;      // e.g. "/Script/Engine.StaticMeshActor"
    FString OuterPath;      // e.g. "/Game/Maps/MyLevel.MyLevel:PersistentLevel"
    FString Label;
    int32 PropertyCount = 0;
    int32 FunctionCount = 0;
    TArray<FDccMcpPropertyDescriptor> Properties;
    TArray<FDccMcpFunctionDescriptor> Functions;
    TArray<FString> Tags;
    TSharedPtr<FJsonObject> Metadata;

    TSharedPtr<FJsonObject> ToJson() const;
};

/**
 * Secure UObject reflection layer.
 *
 * All operations are checked against FDccMcpSecurity BEFORE any UObject is
 * touched. This class is the single entry point for all reflection operations.
 *
 * Design invariants:
 * - All UObject mutations are dispatched via AsyncTask(ENamedThreads::GameThread, ...).
 * - All read operations are marked const and do not modify UObjects.
 * - Security checks happen synchronously; only the actual UObject access
 *   may be dispatched to GameThread.
 */
class DCCMCPUNREAL_API FDccMcpReflection
{
public:
    /** Discover UObjects in the current editor world. */
    static TArray<FDccMcpObjectDescriptor> DiscoverObjects(
        const FString& ClassFilter,
        const FString& OuterFilter,
        int32 MaxResults
    );

    /** Get detailed reflection info for a single UObject. */
    static FDccMcpObjectDescriptor DescribeObject(
        const FString& ObjectPath,
        bool bIncludeProperties,
        bool bIncludeFunctions
    );

    /** Read a single property value. */
    static TSharedPtr<FJsonObject> GetProperty(
        const FString& ObjectPath,
        const FString& PropertyName
    );

    /** Read multiple property values. */
    static TArray<TSharedPtr<FJsonValue>> GetProperties(
        const FString& ObjectPath,
        const TArray<FString>& PropertyNames
    );

    /** Write a single property value. MUST be called from GameThread. */
    static TSharedPtr<FJsonObject> SetProperty(
        const FString& ObjectPath,
        const FString& PropertyName,
        const TSharedPtr<FJsonValue>& Value
    );

    /** Write multiple property values. MUST be called from GameThread. */
    static TArray<TSharedPtr<FJsonValue>> SetProperties(
        const FString& ObjectPath,
        const TSharedPtr<FJsonObject>& Properties
    );

    /** Call a UFunction. MUST be called from GameThread. */
    static TSharedPtr<FJsonObject> CallFunction(
        const FString& ObjectPath,
        const FString& FunctionName,
        const TSharedPtr<FJsonObject>& Args,
        int32 TimeoutMs
    );

private:
    /** Resolve a UObject from its path. */
    static UObject* ResolveObject(const FString& ObjectPath);

    /** Extract property descriptors from a UClass. */
    static TArray<FDccMcpPropertyDescriptor> ExtractProperties(UClass* Class, UObject* Instance);

    /** Extract function descriptors from a UClass. */
    static TArray<FDccMcpFunctionDescriptor> ExtractFunctions(UClass* Class);

    /** Guess the semantic category of a property. */
    static FString GuessPropertyCategory(FProperty* Property);

    /** Extract human-readable property flags. */
    static TArray<FString> ExtractPropertyFlags(FProperty* Property);
};
