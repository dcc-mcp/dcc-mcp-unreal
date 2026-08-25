using System;
using System.Collections;
using System.IO;
using UnrealBuildTool;

public class DccMcpUnreal : ModuleRules
{
    public DccMcpUnreal(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

        // An in-place UE 5.8.1 launcher update can leave the installed 5.8.0
        // engine reflection output behind. The packaging layer detects that
        // exact source/generated-header mismatch and supplies job-scoped macro
        // aliases without modifying the Epic installation.
        string generatedHeaderCompat = Environment.GetEnvironmentVariable(
            "DCC_MCP_UNREAL_GENERATED_HEADER_COMPAT"
        );
        if (!String.IsNullOrEmpty(generatedHeaderCompat) && File.Exists(generatedHeaderCompat))
        {
            // UE 4.18 does not define NoPCHs, so resolve it only when the
            // UE 5.8 compatibility path is active instead of referencing the
            // newer enum member while compiling legacy module rules.
            PCHUsage = (PCHUsageMode)Enum.Parse(typeof(PCHUsageMode), "NoPCHs");
            var forceIncludeProperty = GetType().GetProperty("ForceIncludeFiles");
            var forceIncludeFiles = forceIncludeProperty == null
                ? null
                : forceIncludeProperty.GetValue(this, null) as IList;
            if (forceIncludeFiles == null)
            {
                throw new BuildException("This UnrealBuildTool cannot apply generated-header compatibility safely.");
            }
            forceIncludeFiles.Add(generatedHeaderCompat);
        }

        PrivateDependencyModuleNames.AddRange(
            new string[]
            {
                "Core",
                "CoreUObject",
                "ApplicationCore",
                "AIModule",
                "Engine",
                "InputCore",
                "AssetRegistry",
                "Json",
                "Networking",
                "Projects",
                "Sockets",
                "Slate",
                "SlateCore",
                "UnrealEd",
            }
        );

        // UE 4.18 has neither Chaos nor GeometryCollectionEngine.
        var versionProperty = Target.GetType().GetProperty("Version");
        if (versionProperty != null &&
            (int)versionProperty.PropertyType.GetProperty("MajorVersion").GetValue(versionProperty.GetValue(Target, null), null) >= 5)
        {
            PrivateDependencyModuleNames.AddRange(new string[] { "GeometryCollectionEngine", "Chaos" });
        }
    }
}
