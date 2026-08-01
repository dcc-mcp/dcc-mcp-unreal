#pragma once

#include "Kismet/BlueprintFunctionLibrary.h"

#include "DccMcpAutomationLibrary.generated.h"

UCLASS()
class DCCMCPUNREAL_API UDccMcpAutomationLibrary : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()

public:
    UFUNCTION(BlueprintCallable, Category = "DCC MCP|Automation")
    static FString ListAutomationTestsJson(const FString& Filter);

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
