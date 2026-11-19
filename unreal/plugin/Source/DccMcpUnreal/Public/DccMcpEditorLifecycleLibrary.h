#pragma once

#include "Kismet/BlueprintFunctionLibrary.h"
#include "DccMcpEditorLifecycleLibrary.generated.h"

// Called only by module startup/shutdown, never by a discoverable tool.
void DccMcpInitializeEditorLifecycle();
void DccMcpShutdownEditorLifecycle();

UCLASS()
class DCCMCPUNREAL_API UDccMcpEditorLifecycleLibrary : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()
public:
    UFUNCTION(BlueprintCallable, Category = "DCC MCP|Editor Lifecycle")
    static FString InspectEditorCloseJson();

    UFUNCTION(BlueprintCallable, Category = "DCC MCP|Editor Lifecycle")
    static FString RequestEditorCloseJson(const FString& GuardJson);

    UFUNCTION(BlueprintCallable, Category = "DCC MCP|Editor Lifecycle")
    static FString GetEditorCloseStatusJson();
};
