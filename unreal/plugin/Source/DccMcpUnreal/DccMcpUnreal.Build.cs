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
    }
}
