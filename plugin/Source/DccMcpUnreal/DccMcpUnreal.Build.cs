// Copyright (c) dcc-mcp contributors. All Rights Reserved.
// SPDX-License-Identifier: MIT

using UnrealBuildTool;

public class DccMcpUnreal : ModuleRules
{
    public DccMcpUnreal(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

        PublicDependencyModuleNames.AddRange(new string[]
        {
            "Core",
            "CoreUObject",
            "Engine",
            "InputCore",
            "Json",
            "JsonUtilities",
        });

        PrivateDependencyModuleNames.AddRange(new string[]
        {
            "Slate",
            "SlateCore",
            "UnrealEd",
            "EditorSubsystem",
        });

        // UE 5.1+ HTTP server module (optional — gated in code)
        if (Target.Version.MajorVersion >= 5 && Target.Version.MinorVersion >= 1)
        {
            PrivateDependencyModuleNames.Add("HTTPServer");
        }

        // UE 4.18 compatibility: skip modules that don't exist in older versions
        if (Target.Version.MajorVersion >= 5 || (Target.Version.MajorVersion == 4 && Target.Version.MinorVersion >= 24))
        {
            // Modules available in 4.24+
        }

        // Editor-only module
        if (Target.bBuildEditor)
        {
            PrivateDependencyModuleNames.Add("EditorFramework");
        }
    }
}
