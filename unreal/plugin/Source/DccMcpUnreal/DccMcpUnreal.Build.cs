using UnrealBuildTool;

public class DccMcpUnreal : ModuleRules
{
    public DccMcpUnreal(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

        PrivateDependencyModuleNames.AddRange(
            new string[]
            {
                "Core",
                "CoreUObject",
                "Engine",
                "AssetRegistry",
                "Json",
                "Networking",
                "Projects",
                "Sockets",
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
