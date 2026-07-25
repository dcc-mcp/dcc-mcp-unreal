// Copyright (c) dcc-mcp contributors. All Rights Reserved.
// SPDX-License-Identifier: MIT

#pragma once

#include "CoreMinimal.h"

/**
 * Fail-closed security policy for UObject reflection.
 *
 * Every reflection operation is validated through this class BEFORE any
 * UObject is accessed. The default state denies everything — explicit
 * allowlists must be configured to enable access.
 *
 * Denial categories:
 * - Private names: properties/functions starting with "_".
 * - Engine internals: classes matching denied patterns (Default__*, Package*, etc.).
 * - Lifecycle functions: BeginPlay, EndPlay, Tick, Destroy, RPC functions.
 * - Sensitive properties: InternalIndex, NativeIndex, etc.
 */
class DCCMCPUNREAL_API FDccMcpSecurity
{
public:
    /** Check whether a class path is accessible. */
    static bool IsClassAllowed(const FString& ClassPath, FString* OutReason = nullptr);

    /** Check whether a property name is allowed to be read. */
    static bool IsPropertyReadAllowed(const FString& PropertyName, const FString& ClassPath, FString* OutReason = nullptr);

    /** Check whether a property write is allowed. */
    static bool IsPropertyWriteAllowed(const FString& PropertyName, const FString& ClassPath, FString* OutReason = nullptr);

    /** Check whether a UFunction call is allowed. */
    static bool IsFunctionCallAllowed(const FString& FunctionName, const FString& ClassPath, FString* OutReason = nullptr);

    /** Check whether the caller is on the GameThread (required for mutations). */
    static bool IsOnGameThread(FString* OutReason = nullptr);

    /** Global switch: enable/disable all property writes. */
    static bool bAllowPropertyWrite;

    /** Global switch: enable/disable all UFunction calls. */
    static bool bAllowFunctionCall;

    /** Global switch: enforce GameThread for mutations. */
    static bool bEnforceGameThread;

private:
    /** Denied class path patterns. */
    static TArray<FString> GetDeniedClassPatterns();

    /** Denied property names. */
    static TArray<FString> GetDeniedPropertyNames();

    /** Denied function name patterns. */
    static TArray<FString> GetDeniedFunctionPatterns();

    /** Denied name prefixes (e.g. "_"). */
    static TArray<FString> GetDeniedPrefixes();
};
