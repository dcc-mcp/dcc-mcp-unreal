#pragma once

#include "Kismet/BlueprintFunctionLibrary.h"
#include "DccMcpEditorWindowLibrary.generated.h"

// Bootstrap identity metadata only; this does not authorize observation or input.
UCLASS()
class DCCMCPUNREAL_API UDccMcpEditorWindowLibrary : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()

public:
    UFUNCTION(BlueprintCallable, Category = "DCC MCP|Editor Identity")
    static FString GetMainFrameIdentityJson();
};
