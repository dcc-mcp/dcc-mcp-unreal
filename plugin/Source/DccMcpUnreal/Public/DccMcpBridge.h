// Copyright (c) dcc-mcp contributors. All Rights Reserved.
// SPDX-License-Identifier: MIT

#pragma once

#include "CoreMinimal.h"
#include "UObject/NoExportTypes.h"

#if (ENGINE_MAJOR_VERSION > 5) || (ENGINE_MAJOR_VERSION == 5 && ENGINE_MINOR_VERSION >= 1)
#include "HttpRouteHandle.h"
class IHttpRouter;
#endif

/**
 * UObject reflection bridge — secure, fail-closed, main-thread-only.
 *
 * This class owns the bridge HTTP endpoint that the Python adapter communicates
 * with. Every reflection operation is validated through FDccMcpSecurity before
 * any UObject is touched.
 *
 * Thread safety:
 * - Read operations: may be dispatched from any thread; the bridge marshals to
 *   GameThread via AsyncTask.
 * - Write/Execute operations: MUST arrive on GameThread. The bridge enforces
 *   this by checking IsInGameThread() and failing closed otherwise.
 */
class DCCMCPUNREAL_API FDccMcpBridge
{
public:
    FDccMcpBridge();
    ~FDccMcpBridge();

    /** Start the bridge HTTP server on the given port. */
    bool StartServer(int32 Port);

    /** Stop the bridge server. */
    void StopServer();

    /** @return true if the server is listening. */
    bool IsRunning() const { return bIsRunning; }

    /** @return the port the server is bound to (0 if not running). */
    int32 GetPort() const { return BoundPort; }

private:
    int32 BoundPort = 0;
    bool bIsRunning = false;

#if (ENGINE_MAJOR_VERSION > 5) || (ENGINE_MAJOR_VERSION == 5 && ENGINE_MINOR_VERSION >= 1)
    TSharedPtr<IHttpRouter> HttpRouter;
    FHttpRouteHandle RouteHandle;
#endif
};
