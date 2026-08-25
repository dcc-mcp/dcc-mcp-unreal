#pragma once

#include "Kismet/BlueprintFunctionLibrary.h"

#include "DccMcpAutomationLibrary.generated.h"

UCLASS()
class DCCMCPUNREAL_API UDccMcpAutomationLibrary : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()

public:
    UFUNCTION(BlueprintPure, Category = "DCC MCP|Capabilities")
    static TArray<FString> GetEnabledPluginNames();

    UFUNCTION(BlueprintCallable, Category = "DCC MCP|Automation")
    static FString ListAutomationTestsJson(const FString& Filter);

    UFUNCTION(BlueprintCallable, Category = "DCC MCP|PIE")
    static bool InjectPieKey(const FString& KeyName, bool bPressed);

    UFUNCTION(BlueprintCallable, Category = "DCC MCP|PIE")
    static bool ClickPiePointerButton(const FString& KeyName, float NormalizedX, float NormalizedY);

    UFUNCTION(BlueprintCallable, Category = "DCC MCP|PIE")
    static bool InjectPieAxis(const FString& KeyName, float Value);

    UFUNCTION(BlueprintCallable, Category = "DCC MCP|PIE")
    static bool InjectPieLook(float DeltaX, float DeltaY);

    UFUNCTION(BlueprintCallable, Category = "DCC MCP|PIE")
    static bool NavigatePieToActor(const FString& ActorName);

    UFUNCTION(BlueprintCallable, Category = "DCC MCP|PIE")
    static bool NavigatePieToLocation(const FVector& TargetLocation);

    UFUNCTION(BlueprintCallable, Category = "DCC MCP|PIE")
    static bool StartPieInputSteering(const FString& ActorName);

    UFUNCTION(BlueprintCallable, Category = "DCC MCP|PIE")
    static bool StartPieInputSteeringToLocation(const FVector& TargetLocation);

    UFUNCTION(BlueprintCallable, Category = "DCC MCP|PIE")
    static bool StopPieNavigation();

    UFUNCTION(BlueprintCallable, Category = "DCC MCP|Fab")
    static FString GetFabSessionStatusJson();

    UFUNCTION(BlueprintCallable, Category = "DCC MCP|Fab")
    static bool RequestFabLogin();

    UFUNCTION(BlueprintCallable, Category = "DCC MCP|Fab")
    static bool OpenFabListing(const FString& ListingUrl);

    UFUNCTION(BlueprintCallable, Category = "DCC MCP|Chaos")
    static FString CreateGeometryCollectionFromStaticMesh(
        const FString& StaticMeshPath,
        const FString& DestinationPath,
        const FString& AssetName,
        float DamageThreshold
    );

    UFUNCTION(BlueprintCallable, Category = "DCC MCP|Chaos")
    static FString SpawnGeometryCollectionActor(
        const FString& GeometryCollectionPath,
        float LocationX,
        float LocationY,
        float LocationZ,
        float DamageThreshold,
        const FString& Label
    );
};
