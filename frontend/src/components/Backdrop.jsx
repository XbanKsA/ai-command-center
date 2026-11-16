function Backdrop() {
  return (
    <>
      <div className="pointer-events-none absolute -left-[12rem] -top-[15rem] -z-10 h-[40rem] w-[48rem] rounded-full bg-glow-a blur-[6rem]" />
      <div className="pointer-events-none absolute -bottom-[17rem] -right-[14rem] -z-10 h-[41rem] w-[49rem] rounded-full bg-glow-b blur-[6rem]" />
    </>
  )
}

export default Backdrop