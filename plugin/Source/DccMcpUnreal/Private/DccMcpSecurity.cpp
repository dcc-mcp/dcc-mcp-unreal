// Copyright (c) dcc-mcp contributors. All Rights Reserved.
// SPDX-License-Identifier: MIT

#include "DccMcpSecurity.h"
#include "Misc/EngineVersionComparison.h"

// ── Global switches (modifiable at runtime) ─────────────────────────────────

bool FDccMcpSecurity::bAllowPropertyWrite = false;
bool FDccMcpSecurity::bAllowFunctionCall = false;
bool FDccMcpSecurity::bEnforceGameThread = true;

// ── Denial lists ────────────────────────────────────────────────────────────

TArray<FString> FDccMcpSecurity::GetDeniedPrefixes()
{
    return {
        TEXT("_"),
        TEXT("bOverride_"),
        TEXT("K2Node_"),
        TEXT("ExecuteUbergraph_"),
    };
}

TArray<FString> FDccMcpSecurity::GetDeniedClassPatterns()
{
    return {
        TEXT("*/Default__*"),
        TEXT("*/Package*"),
        TEXT("*/Class*"),
        TEXT("*/MetaData*"),
        TEXT("*/PlayerController*"),
        TEXT("*/GameModeBase*"),
        TEXT("*/GameStateBase*"),
        TEXT("*/WorldSettings*"),
    };
}

TArray<FString> FDccMcpSecurity::GetDeniedPropertyNames()
{
    return {
        TEXT("bIsEditorOnly"),
        TEXT("InternalIndex"),
        TEXT("NativeIndex"),
    };
}

TArray<FString> FDccMcpSecurity::GetDeniedFunctionPatterns()
{
    return {
        TEXT("*/K2_DestroyActor"),
        TEXT("*/K2_DestroyComponent"),
        TEXT("*/Server_*"),
        TEXT("*/Client_*"),
        TEXT("*/Multicast_*"),
        TEXT("*/OnRep_*"),
        TEXT("*/BeginPlay"),
        TEXT("*/EndPlay"),
        TEXT("*/Tick"),
        TEXT("*/ReceiveTick"),
        TEXT("*/ReceiveBeginPlay"),
        TEXT("*/ReceiveEndPlay"),
        TEXT("*/ReceiveDestroyed"),
        TEXT("*/ReceiveActorBeginOverlap"),
        TEXT("*/ReceiveActorEndOverlap"),
        TEXT("*/ReceiveHit"),
        TEXT("*/UserConstructionScript"),
        TEXT("*/ReceiveAnyDamage"),
        TEXT("*/ReceivePointDamage"),
        TEXT("*/ReceiveRadialDamage"),
        TEXT("*/BndEvt__*"),
    };
}

// ── Check helpers ───────────────────────────────────────────────────────────

static bool MatchesPrefix(const FString& Name, const TArray<FString>& Prefixes)
{
    for (const FString& Prefix : Prefixes)
    {
        if (Name.StartsWith(Prefix))
        {
            return true;
        }
    }
    return false;
}

static bool MatchesPattern(const FString& Value, const FString& Pattern)
{
    // Simple glob: * matches any sequence, ? matches any single char.
    const TCHAR* VP = *Value;
    const TCHAR* PP = *Pattern;
    const TCHAR* VStar = nullptr;
    const TCHAR* PStar = nullptr;

    while (*VP)
    {
        if (*PP == TEXT('*'))
        {
            VStar = VP;
            PStar = ++PP;
        }
        else if (*PP == TEXT('?') || *PP == *VP)
        {
            ++VP;
            ++PP;
        }
        else if (PStar)
        {
            VP = ++VStar;
            PP = PStar;
        }
        else
        {
            return false;
        }
    }

    while (*PP == TEXT('*')) { ++PP; }
    return !*PP;
}

// ── Public API ──────────────────────────────────────────────────────────────

bool FDccMcpSecurity::IsClassAllowed(const FString& ClassPath, FString* OutReason)
{
    // Check denied prefixes
    TArray<FString> Prefixes = GetDeniedPrefixes();
    if (MatchesPrefix(ClassPath, Prefixes))
    {
        if (OutReason) *OutReason = FString::Printf(TEXT("Class %s matches denied prefix"), *ClassPath);
        return false;
    }

    // Check denied class patterns
    for (const FString& Pattern : GetDeniedClassPatterns())
    {
        if (MatchesPattern(ClassPath, Pattern))
        {
            if (OutReason) *OutReason = FString::Printf(TEXT("Class %s matches denied pattern %s"), *ClassPath, *Pattern);
            return false;
        }
    }

    return true;
}

bool FDccMcpSecurity::IsPropertyReadAllowed(const FString& PropertyName, const FString& ClassPath, FString* OutReason)
{
    if (!IsClassAllowed(ClassPath, OutReason))
    {
        return false;
    }

    // Check denied prefixes
    if (MatchesPrefix(PropertyName, GetDeniedPrefixes()))
    {
        if (OutReason) *OutReason = FString::Printf(TEXT("Property %s starts with denied prefix"), *PropertyName);
        return false;
    }

    // Check denied property names
    for (const FString& Denied : GetDeniedPropertyNames())
    {
        if (PropertyName.Equals(Denied, ESearchCase::IgnoreCase))
        {
            if (OutReason) *OutReason = FString::Printf(TEXT("Property %s is in the denied list"), *PropertyName);
            return false;
        }
    }

    return true;
}

bool FDccMcpSecurity::IsPropertyWriteAllowed(const FString& PropertyName, const FString& ClassPath, FString* OutReason)
{
    if (!bAllowPropertyWrite)
    {
        if (OutReason) *OutReason = TEXT("Property writes are globally disabled (bAllowPropertyWrite=false)");
        return false;
    }

    if (!IsPropertyReadAllowed(PropertyName, ClassPath, OutReason))
    {
        return false;
    }

    return true;
}

bool FDccMcpSecurity::IsFunctionCallAllowed(const FString& FunctionName, const FString& ClassPath, FString* OutReason)
{
    if (!bAllowFunctionCall)
    {
        if (OutReason) *OutReason = TEXT("Function calls are globally disabled (bAllowFunctionCall=false)");
        return false;
    }

    if (!IsClassAllowed(ClassPath, OutReason))
    {
        return false;
    }

    // Check denied prefixes
    if (MatchesPrefix(FunctionName, GetDeniedPrefixes()))
    {
        if (OutReason) *OutReason = FString::Printf(TEXT("Function %s starts with denied prefix"), *FunctionName);
        return false;
    }

    // Check denied function patterns
    FString FuncPath = FString::Printf(TEXT("%s::%s"), *ClassPath, *FunctionName);
    for (const FString& Pattern : GetDeniedFunctionPatterns())
    {
        if (MatchesPattern(FuncPath, Pattern) || MatchesPattern(FunctionName, Pattern))
        {
            if (OutReason) *OutReason = FString::Printf(TEXT("Function %s matches denied pattern %s"), *FunctionName, *Pattern);
            return false;
        }
    }

    return true;
}

bool FDccMcpSecurity::IsOnGameThread(FString* OutReason)
{
    if (!bEnforceGameThread)
    {
        return true;
    }

    if (!IsInGameThread())
    {
        if (OutReason) *OutReason = TEXT("Operation requires GameThread but is running on a different thread");
        return false;
    }

    return true;
}
