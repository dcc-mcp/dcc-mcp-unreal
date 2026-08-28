// Independent behavioral API shim, not Unreal headers and not a live host.
#include <algorithm>
#include <cmath>
#include <functional>
#include <iostream>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>
#include <utility>
#include <limits>
#define TEXT(x) x
using int32 = int;
struct FString : std::string {
    using std::string::string;
    FString() = default;
    FString(const std::string& value):std::string(value){}
    const char* operator*() const { return c_str(); }
    bool IsEmpty() const { return empty(); }
};
struct FName { std::string value; explicit FName(const char* v):value(v){} };
struct FKey {
    std::string value;
    FKey() = default;
    explicit FKey(FName v):value(v.value){}
    bool IsValid() const { return !value.empty(); }
    bool operator==(const FKey& other) const { return value==other.value; }
};
enum EInputEvent { IE_Pressed, IE_Released };
struct FInputDeviceId { int value=17; };
struct FInputKeyParams {
    FKey Key; EInputEvent Event; double Value; FInputDeviceId Device;
    FInputKeyParams(FKey k,EInputEvent e,double v,bool,FInputDeviceId d):Key(k),Event(e),Value(v),Device(d){}
};
struct IPlatformInputDeviceMapper {
    static IPlatformInputDeviceMapper& Get(){ static IPlatformInputDeviceMapper x; return x; }
    FInputDeviceId GetPrimaryInputDeviceForUser(int) { return {}; }
};
struct FGuid { static FGuid NewGuid(){ return {}; } FString ToString(){ static int n=0; return std::to_string(++n); } };
template<class T> struct TArray : std::vector<T> {
    using std::vector<T>::vector;
    bool Contains(const T& value) const { return std::find(this->begin(),this->end(),value)!=this->end(); }
    int Num() const { return static_cast<int>(this->size()); }
    T& Last(){ return this->back(); }
};
template<class K,class V> struct TMap {
    std::map<K,V> rows;
    struct Iterator {
        TMap* owner; typename std::map<K,V>::iterator pos; bool erased=false;
        explicit operator bool() const { return pos!=owner->rows.end(); }
        Iterator& operator++(){ if(erased) erased=false; else ++pos; return *this; }
        V& Value(){ return pos->second; }
        void RemoveCurrent(){ pos=owner->rows.erase(pos); erased=true; }
    };
    Iterator CreateIterator(){ return {this,rows.begin()}; }
    int Num() const { return static_cast<int>(rows.size()); }
    void Add(K key,V value){ rows.emplace(std::move(key),std::move(value)); }
    V* Find(const K& key){ auto it=rows.find(key); return it==rows.end()?nullptr:&it->second; }
    bool RemoveAndCopyValue(const K& key,V& value){ auto it=rows.find(key); if(it==rows.end()) return false; value=it->second; rows.erase(it); return true; }
};
struct UObject { bool valid=true; virtual ~UObject() = default; };
template<class T> bool IsValid(T* value){ return value && value->valid; }
template<class T> struct TWeakObjectPtr {
    T* value=nullptr;
    TWeakObjectPtr()=default; TWeakObjectPtr(T* v):value(v){}
    T* Get() const { return ::IsValid(value)?value:nullptr; }
    bool IsValid() const { return Get()!=nullptr; }
    T* operator->() const { return Get(); }
};
enum class EWorldType { PIE, Game, GamePreview, Editor };
struct UWorld:UObject { EWorldType WorldType=EWorldType::PIE; };
struct FRotator { double Pitch=0,Yaw=0,Roll=0; FRotator()=default; FRotator(double p,double y,double r):Pitch(p),Yaw(y),Roll(r){} };
struct FVector {
    double X=0,Y=0,Z=0; FVector()=default; FVector(double x,double y,double z):X(x),Y(y),Z(z){}
    bool ContainsNaN() const { return !std::isfinite(X)||!std::isfinite(Y)||!std::isfinite(Z); }
    FVector operator-(const FVector& r) const { return {X-r.X,Y-r.Y,Z-r.Z}; }
    bool Normalize(){ double d=std::sqrt(X*X+Y*Y+Z*Z); if(d<1e-8)return false; X/=d;Y/=d;Z/=d;return true; }
    FRotator Rotation() const { return {0,std::atan2(Y,X)*180/3.141592653589793,0}; }
    static double DistSquared2D(const FVector&a,const FVector&b){ return (a.X-b.X)*(a.X-b.X)+(a.Y-b.Y)*(a.Y-b.Y); }
};
namespace FMath { template<class T> auto Abs(T v){return std::abs(v);} template<class T> T Square(T v){return v*v;} }
struct AActor:UObject { UWorld* world=nullptr; FVector location; UWorld* GetWorld() const {return world;} FVector GetActorLocation() const {return location;} };
struct APawn:AActor { int moves=0; void AddMovementInput(FVector,double,bool){++moves;} };
struct UPlayerInput;
struct APlayerController:AActor {
    std::function<void()> on_turn,on_read_rotation;
    APawn* pawn=nullptr; UPlayerInput* PlayerInput=nullptr; bool local=true; int stops=0,turns=0; FRotator rotation;
    APawn* GetPawn(){return pawn;} bool IsLocalController(){return local;} int GetPlatformUserId(){return 1;}
    void StopMovement(){++stops;} FRotator GetControlRotation(){if(on_read_rotation)on_read_rotation();return rotation;}
    void SetControlRotation(FRotator value){rotation=value;++turns;if(on_turn)on_turn();}
};
struct UPlayerInput:UObject {
    APlayerController* outer=nullptr; int down=0,up=0; bool consumed=false; std::function<void()> on_event;
    UObject* GetOuter(){return outer;}
    bool InputKey(FKey,EInputEvent event,float,bool){ if(event==IE_Pressed)++down;else ++up; if(on_event)on_event();return consumed; }
    bool InputKey(FInputKeyParams p){return InputKey(p.Key,p.Event,static_cast<float>(p.Value),false);}
};
bool game_thread=true;
bool IsInGameThread(){return game_thread;}
struct FDelegateHandle {int id=0;bool IsValid()const{return id!=0;}void Reset(){id=0;} };
struct FTickerDelegate { template<class F>static std::function<bool(float)> CreateLambda(F fn){return fn;} };
struct FTicker {
    using FDelegateHandle=::FDelegateHandle;
    int sequence=0; std::map<int,std::function<bool(float)>> callbacks;
    static FTicker& GetCoreTicker(){static FTicker x;return x;}
    FDelegateHandle AddTicker(std::function<bool(float)> fn){int id=++sequence;callbacks[id]=fn;return {id};}
    void RemoveTicker(FDelegateHandle handle){callbacks.erase(handle.id);}
    void Tick(){auto copy=callbacks;for(auto& pair:copy)if(callbacks.count(pair.first)&&!pair.second(0.016f))callbacks.erase(pair.first);}
};
using FTSTicker=FTicker;
template<class T> using TSharedRef=std::shared_ptr<T>;
template<class T> std::shared_ptr<T> MakeShareable(T* value){return std::shared_ptr<T>(value);}
template<class T> auto MoveTemp(T& value)->decltype(std::move(value)){return std::move(value);}
struct UAIBlueprintHelperLibrary {
    static inline APlayerController* receiver=nullptr;
    static void SimpleMoveToLocation(APlayerController* c,const FVector&){receiver=c;}
    static void SimpleMoveToActor(APlayerController* c,AActor*){receiver=c;}
};
using UNavigationSystem=UAIBlueprintHelperLibrary;
struct UDccMcpAutomationLibrary {
    static FString AcquirePieKey(UWorld*,APlayerController*,const FString&);
    static bool PressOwnedPieKey(const FString&);
    static bool ReleaseOwnedPieKey(const FString&);
    static bool NavigateOwnedPieToLocation(UWorld*,APlayerController*,APawn*,const FVector&);
    static bool NavigateOwnedPieToActor(UWorld*,APlayerController*,APawn*,AActor*);
    static bool StartOwnedPieInputSteeringToLocation(UWorld*,APlayerController*,APawn*,const FVector&);
    static bool StopOwnedPieNavigation(UWorld*,APlayerController*,APawn*);
};
int resolver_calls=0;
APlayerController* GetPiePlayerController(){++resolver_calls;throw std::runtime_error("forbidden current-controller resolver");}
