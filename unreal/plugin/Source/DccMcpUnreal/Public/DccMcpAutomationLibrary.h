#pragma once

#include "Kismet/BlueprintFunctionLibrary.h"

#include "DccMcpAutomationLibrary.generated.h"

class APlayerController;
class AActor;
class APawn;
class UWorld;

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

    // Internal bounded playtest ownership; no current-controller or Slate fallback.
    UFUNCTION(BlueprintCallable, Category = "DCC MCP|PIE")
    static FString AcquirePieKey(UWorld* World, APlayerController* Controller, const FString& KeyName);

    UFUNCTION(BlueprintCallable, Category = "DCC MCP|PIE")
    static bool PressOwnedPieKey(const FString& Owner);

    UFUNCTION(BlueprintCallable, Category = "DCC MCP|PIE")
    static bool ReleaseOwnedPieKey(const FString& Owner);

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

    UFUNCTION(BlueprintCallable, Category = "DCC MCP|PIE")
    static bool StopOwnedPieNavigation(UWorld* World, APlayerController* Controller, APawn* Pawn);

    UFUNCTION(BlueprintCallable, Category = "DCC MCP|PIE")
    static bool NavigateOwnedPieToLocation(UWorld* World, APlayerController* Controller, APawn* Pawn, const FVector& TargetLocation);

    UFUNCTION(BlueprintCallable, Category = "DCC MCP|PIE")
    static bool NavigateOwnedPieToActor(UWorld* World, APlayerController* Controller, APawn* Pawn, AActor* TargetActor);

    UFUNCTION(BlueprintCallable, Category = "DCC MCP|PIE")
    static bool StartOwnedPieInputSteeringToLocation(UWorld* World, APlayerController* Controller, APawn* Pawn, const FVector& TargetLocation);

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
