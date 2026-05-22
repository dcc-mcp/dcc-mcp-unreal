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
};
