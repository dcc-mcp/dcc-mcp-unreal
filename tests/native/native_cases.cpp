// Appended to exact production bodies by scripts/check_playtest_native.py.
using L=UDccMcpAutomationLibrary;
void check(bool value,const char* message){if(!value)throw std::runtime_error(message);}
struct Fixture {
    UWorld world,other; APawn pawn,replacement; APlayerController controller,other_controller; UPlayerInput input,replaced_input;
    Fixture(){
        OwnedPieKeys.rows.clear();FTicker::GetCoreTicker().callbacks.clear();PieInputSteeringTickerHandle.Reset();
        PieSteeringWorld=nullptr;PieSteeringController=nullptr;PieSteeringPawn=nullptr;game_thread=true;resolver_calls=0;
        pawn.world=replacement.world=controller.world=&world;controller.pawn=&pawn;controller.PlayerInput=&input;
        other_controller.world=&other;input.outer=replaced_input.outer=&controller;UAIBlueprintHelperLibrary::receiver=nullptr;
    }
};
void keys_captured_release(){
    Fixture f;auto owner=L::AcquirePieKey(&f.world,&f.controller,"W");check(!owner.empty(),"acquire");
    check(L::PressOwnedPieKey(owner),"unconsumed key is still accepted");
    f.controller.PlayerInput=&f.replaced_input;f.controller.pawn=&f.replacement;
    check(L::ReleaseOwnedPieKey(owner),"release captured receiver after drift");
    check(f.input.down==1&&f.input.up==1&&f.replaced_input.up==0,"key-up receiver isolation");
    check(!L::ReleaseOwnedPieKey(owner)&&f.input.up==1,"consume once");
}
void keys_overlap_capacity(){
    Fixture f;auto first=L::AcquirePieKey(&f.world,&f.controller,"W");
    check(L::AcquirePieKey(&f.world,&f.controller,"W").empty(),"duplicate receiver/key refused");
    check(!L::AcquirePieKey(&f.world,&f.controller,"A").empty(),"different key permitted");
    check(L::ReleaseOwnedPieKey(first)&&f.input.up==0,"unpressed key no release delivery");
    std::vector<std::unique_ptr<APlayerController>> cs;std::vector<std::unique_ptr<UPlayerInput>> ins;
    while(OwnedPieKeys.Num()<128){auto c=std::make_unique<APlayerController>();auto i=std::make_unique<UPlayerInput>();c->world=&f.world;c->pawn=&f.pawn;i->outer=c.get();c->PlayerInput=i.get();check(!L::AcquirePieKey(&f.world,c.get(),"W").empty(),"within capacity");cs.push_back(std::move(c));ins.push_back(std::move(i));}
    check(L::AcquirePieKey(&f.world,&f.controller,"D").empty(),"capacity bound");
    ins.front()->valid=false;check(!L::AcquirePieKey(&f.world,&f.controller,"D").empty(),"invalid receiver reclaimed");
}
void keys_press_drift(){
    Fixture f;auto o=L::AcquirePieKey(&f.world,&f.controller,"W");f.controller.PlayerInput=&f.replaced_input;
    check(!L::PressOwnedPieKey(o)&&f.input.down==0&&f.replaced_input.down==0,"reject replaced input");check(L::ReleaseOwnedPieKey(o),"retire unpressed lease");
    o=L::AcquirePieKey(&f.world,&f.controller,"W");f.controller.pawn=&f.replacement;check(!L::PressOwnedPieKey(o),"reject replaced pawn");
}
void keys_release_consumed_before_throw(){
    Fixture f;auto o=L::AcquirePieKey(&f.world,&f.controller,"W");check(L::PressOwnedPieKey(o),"press");
    f.input.on_event=[](){throw std::runtime_error("receiver interrupted after delivery");};
    try{L::ReleaseOwnedPieKey(o);}catch(const std::runtime_error&){}
    check(OwnedPieKeys.Num()==0&&!L::ReleaseOwnedPieKey(o)&&f.input.up==1,"key up never replayed");
}
void native_entry_guards(){
    Fixture f;FVector point(100,20,0);
    check(L::NavigateOwnedPieToLocation(&f.world,&f.controller,&f.pawn,point),"navigate owned");check(UAIBlueprintHelperLibrary::receiver==&f.controller&&resolver_calls==0,"exact native receiver");
    AActor target;target.world=&f.world;check(L::NavigateOwnedPieToActor(&f.world,&f.controller,&f.pawn,&target),"exact target");
    target.world=&f.other;check(!L::NavigateOwnedPieToActor(&f.world,&f.controller,&f.pawn,&target),"target wrong world");
    check(!L::StartOwnedPieInputSteeringToLocation(&f.other,&f.controller,&f.pawn,point),"wrong bound world");
    f.controller.pawn=&f.replacement;check(!L::StartOwnedPieInputSteeringToLocation(&f.world,&f.controller,&f.pawn,point),"wrong pawn");f.controller.pawn=&f.pawn;
    f.controller.local=false;check(!L::NavigateOwnedPieToLocation(&f.world,&f.controller,&f.pawn,point),"not local");f.controller.local=true;
    f.world.WorldType=EWorldType::Editor;check(!L::NavigateOwnedPieToLocation(&f.world,&f.controller,&f.pawn,point),"not playable");f.world.WorldType=EWorldType::PIE;
    game_thread=false;check(!L::NavigateOwnedPieToLocation(&f.world,&f.controller,&f.pawn,point),"not game thread");game_thread=true;
    check(!L::StartOwnedPieInputSteeringToLocation(&f.world,&f.controller,&f.pawn,FVector(1000001,0,0)),"bounded coordinate");
    check(!L::NavigateOwnedPieToLocation(&f.world,&f.controller,&f.pawn,FVector(std::numeric_limits<double>::infinity(),0,0)),"finite coordinate");
}
void steering_positive_and_pawn_replacement(){
    Fixture f;check(L::StartOwnedPieInputSteeringToLocation(&f.world,&f.controller,&f.pawn,FVector(1000,0,0)),"steering start");
    FTicker::GetCoreTicker().Tick();check(f.pawn.moves==1&&f.controller.turns==1,"bound input delivered");
    f.controller.pawn=&f.replacement;FTicker::GetCoreTicker().Tick();check(f.pawn.moves==1&&f.replacement.moves==0,"replacement not steered");
    check(FTicker::GetCoreTicker().callbacks.empty(),"drift retires callback");
    check(!L::StopOwnedPieNavigation(&f.world,&f.controller,&f.pawn),"stop refuses replacement");check(f.controller.stops==1,"replacement controller stop not called");
}
void steering_stop_exact_and_not_other(){
    Fixture f;check(L::StartOwnedPieInputSteeringToLocation(&f.world,&f.controller,&f.pawn,FVector(1000,0,0)),"start");
    check(!L::StopOwnedPieNavigation(&f.other,&f.other_controller,&f.replacement),"unbound stop refused");
    check(!FTicker::GetCoreTicker().callbacks.empty(),"other receiver stop preserves ticker");
    check(L::StopOwnedPieNavigation(&f.world,&f.controller,&f.pawn),"bound stop");check(FTicker::GetCoreTicker().callbacks.empty(),"owned ticker retired");
}
void steering_retained_objects_cross_world(){
    Fixture f;check(L::StartOwnedPieInputSteeringToLocation(&f.world,&f.controller,&f.pawn,FVector(1000,0,0)),"start");
    FTicker::GetCoreTicker().Tick();check(f.pawn.moves==1,"positive original tick");
    f.controller.world=f.pawn.world=&f.other;FTicker::GetCoreTicker().Tick();
    std::cout<<"  original moves=1; after retained objects travel moves="<<f.pawn.moves<<"; callbacks="<<FTicker::GetCoreTicker().callbacks.size()<<"\n";
    check(f.pawn.moves==1&&FTicker::GetCoreTicker().callbacks.empty(),"owned steering must not inject into a different world");
}
void steering_world_loses_playability(){
    Fixture f;check(L::StartOwnedPieInputSteeringToLocation(&f.world,&f.controller,&f.pawn,FVector(1000,0,0)),"start");
    f.world.WorldType=EWorldType::Editor;FTicker::GetCoreTicker().Tick();
    check(f.pawn.moves==0,"no steering in a nonplayable world");
}
void steering_cleanup_respects_original_world(){
    Fixture f;check(L::StartOwnedPieInputSteeringToLocation(&f.world,&f.controller,&f.pawn,FVector(1000,0,0)),"start A");
    f.controller.world=f.pawn.world=&f.other;
    check(!L::StopOwnedPieNavigation(&f.world,&f.controller,&f.pawn),"old world cleanup cannot stop movement in B");
    check(FTicker::GetCoreTicker().callbacks.empty(),"old world still retires its owned ticker");
    check(L::StartOwnedPieInputSteeringToLocation(&f.other,&f.controller,&f.pawn,FVector(1000,0,0)),"start B");
    check(!L::StopOwnedPieNavigation(&f.world,&f.controller,&f.pawn),"old world cannot stop B");
    check(!FTicker::GetCoreTicker().callbacks.empty(),"A cleanup preserves B owned ticker");
    FTicker::GetCoreTicker().Tick();check(f.pawn.moves==1,"B owned tick still delivered");
}
void steering_rechecks_between_callback_mutations(){
    Fixture f;check(L::StartOwnedPieInputSteeringToLocation(&f.world,&f.controller,&f.pawn,FVector(1000,0,0)),"start");
    f.controller.on_turn=[&](){f.controller.world=f.pawn.world=&f.other;};
    FTicker::GetCoreTicker().Tick();
    check(f.controller.turns==1&&f.pawn.moves==0,"reentrant drift after rotation prevents movement");
    check(FTicker::GetCoreTicker().callbacks.empty(),"reentrant drift retires callback");
}
void steering_rechecks_before_rotation(){
    Fixture f;check(L::StartOwnedPieInputSteeringToLocation(&f.world,&f.controller,&f.pawn,FVector(1000,0,0)),"start");
    f.controller.on_read_rotation=[&](){f.controller.world=f.pawn.world=&f.other;};
    FTicker::GetCoreTicker().Tick();
    check(f.controller.turns==0&&f.pawn.moves==0,"drift during rotation read prevents both mutations");
}
void steering_invalid_world_or_nonlocal_controller(){
    Fixture f;check(L::StartOwnedPieInputSteeringToLocation(&f.world,&f.controller,&f.pawn,FVector(1000,0,0)),"start");
    f.world.valid=false;FTicker::GetCoreTicker().Tick();check(f.pawn.moves==0,"dead world blocks tick");
    f.world.valid=true;check(L::StartOwnedPieInputSteeringToLocation(&f.world,&f.controller,&f.pawn,FVector(1000,0,0)),"restart");
    f.controller.local=false;FTicker::GetCoreTicker().Tick();check(f.pawn.moves==0,"nonlocal controller blocks tick");
}
int main(){
    int failed=0,passed=0;
    const std::vector<std::pair<const char*,std::function<void()>>> cases={
        {"keys_captured_release",keys_captured_release},{"keys_overlap_capacity",keys_overlap_capacity},
        {"keys_press_drift",keys_press_drift},{"keys_release_consumed_before_throw",keys_release_consumed_before_throw},
        {"native_entry_guards",native_entry_guards},{"steering_positive_and_pawn_replacement",steering_positive_and_pawn_replacement},
        {"steering_stop_exact_and_not_other",steering_stop_exact_and_not_other},
        {"steering_retained_objects_cross_world",steering_retained_objects_cross_world},
        {"steering_world_loses_playability",steering_world_loses_playability},
        {"steering_cleanup_respects_original_world",steering_cleanup_respects_original_world},
        {"steering_rechecks_between_callback_mutations",steering_rechecks_between_callback_mutations},
        {"steering_rechecks_before_rotation",steering_rechecks_before_rotation},
        {"steering_invalid_world_or_nonlocal_controller",steering_invalid_world_or_nonlocal_controller}};
    for(auto& item:cases){try{item.second();++passed;std::cout<<"PASS "<<item.first<<"\n";}catch(const std::exception&e){++failed;std::cout<<"FAIL "<<item.first<<": "<<e.what()<<"\n";}}
    std::cout<<"ABI shim "<<ENGINE_MAJOR_VERSION<<"."<<ENGINE_MINOR_VERSION<<" passed="<<passed<<" failed="<<failed<<"\n";
    return failed?1:0;
}
